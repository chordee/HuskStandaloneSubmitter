'''
Submit jobs to Deadline through deadlinecommand.
'''
from __future__ import annotations

import logging
import os
import re
import shutil
import subprocess
import sys
import tempfile
from dataclasses import dataclass
from pathlib import Path

from .jobs import Job

logger = logging.getLogger(__name__)

PLUGIN_NAME = 'HuskStandalone'
MACOS_DEADLINE_PATH_FILE = Path('/Users/Shared/Thinkbox/DEADLINE_PATH')
JOB_ID_PATTERN = re.compile(r'^JobID=(\S+)', re.MULTILINE)


class DeadlineError(Exception):
	'''Raised when deadlinecommand cannot be found or run.'''


@dataclass
class SubmitResult:
	job: Job
	success: bool
	job_id: str
	output: str


def find_deadlinecommand() -> Path:
	'''
	Locate deadlinecommand via DEADLINE_PATH, the macOS DEADLINE_PATH file or PATH.
	'''
	executable = 'deadlinecommand.exe' if sys.platform == 'win32' else 'deadlinecommand'
	directories = [os.environ.get('DEADLINE_PATH', '')]
	if MACOS_DEADLINE_PATH_FILE.is_file():
		directories.append(MACOS_DEADLINE_PATH_FILE.read_text().strip())

	for directory in filter(None, directories):
		candidate = Path(directory) / executable
		if candidate.is_file():
			return candidate

	found = shutil.which('deadlinecommand')
	if found:
		return Path(found)
	raise DeadlineError('deadlinecommand not found. Set DEADLINE_PATH or add it to PATH.')


def parse_environment(text: str) -> dict[str, str]:
	'''
	Environment variables from KEY=VALUE lines. Blank lines are ignored.
	'''
	environment = {}
	for line in filter(None, (line.strip() for line in text.splitlines())):
		key, separator, value = line.partition('=')
		if not separator or not key.strip():
			raise ValueError(f'Invalid environment variable {line!r}, expected KEY=VALUE')
		environment[key.strip()] = value.strip()
	return environment


def rez_entries(rez: str) -> dict[str, str]:
	'''
	Plugin info entries running husk in a rez context file (.rxt) or package request.
	'''
	rez = rez.strip()
	if not rez:
		return {}
	return {'RezContext' if rez.lower().endswith('.rxt') else 'RezRequest': rez}


def job_info(
		job: Job, batch_name: str = '', comment: str = '', chunk_size: int = 1,
		environment: dict[str, str] | None = None) -> dict[str, str]:
	'''
	Deadline job info entries. OutputFilenameN lets the Monitor browse outputs,
	EnvironmentKeyValueN are set when the Worker renders the job.
	'''
	entries = {
		'Plugin': PLUGIN_NAME,
		'Name': job.name,
		'Comment': comment,
		'Frames': job.frames,
		'ChunkSize': str(chunk_size),
	}
	if batch_name:
		entries['BatchName'] = batch_name
	entries.update({f'OutputFilename{index}': output for index, output in enumerate(job.outputs)})
	entries.update({
		f'EnvironmentKeyValue{index}': f'{key}={value}'
		for index, (key, value) in enumerate((environment or {}).items())})
	return entries


def plugin_info(job: Job, houdini_version: str = '', rez: str = '') -> dict[str, str]:
	'''
	Plugin info entries. ArgumentList tells HuskStandalone.py which entries
	are husk arguments; Version selects the husk executable unless husk runs in rez.
	'''
	entries = {'ArgumentList': ';'.join(job.plugin_info)}
	entries.update(job.plugin_info)
	if houdini_version:
		entries['Version'] = houdini_version
	entries.update(rez_entries(rez))
	return entries


def write_info_file(path: Path, entries: dict[str, str]) -> None:
	'''
	Write key=value lines in UTF-16, matching the Monitor submission scripts.
	'''
	path.write_text(''.join(f'{key}={value}\n' for key, value in entries.items()), encoding='utf-16')


def submit_job(
		job: Job, deadlinecommand: Path, batch_name: str = '', comment: str = '',
		chunk_size: int = 1, houdini_version: str = '',
		environment: dict[str, str] | None = None, rez: str = '') -> SubmitResult:
	with tempfile.TemporaryDirectory(prefix='husk_submit_') as directory:
		job_file = Path(directory) / 'job_info.job'
		plugin_file = Path(directory) / 'plugin_info.job'
		write_info_file(job_file, job_info(job, batch_name, comment, chunk_size, environment))
		write_info_file(plugin_file, plugin_info(job, houdini_version, rez))

		try:
			# CREATE_NO_WINDOW only exists on Windows, where it avoids a console popping up
			process = subprocess.run(
				[str(deadlinecommand), str(job_file), str(plugin_file)],
				capture_output=True, text=True, check=False,
				creationflags=getattr(subprocess, 'CREATE_NO_WINDOW', 0))
		except OSError as error:
			raise DeadlineError(f'Failed to run {deadlinecommand}: {error}') from error

	output = process.stdout + process.stderr
	success = process.returncode == 0 and 'Result=Success' in output
	match = JOB_ID_PATTERN.search(output)
	if not success:
		logger.error('Submitting %s failed:\n%s', job.name, output)
	return SubmitResult(job, success, match.group(1) if match else '', output)
