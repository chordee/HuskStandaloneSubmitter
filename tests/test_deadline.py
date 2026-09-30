from __future__ import annotations

import stat
import sys
from pathlib import Path

import pytest

from husk_submitter import deadline
from husk_submitter.jobs import Job


@pytest.fixture
def job() -> Job:
	return Job(
		name='shot.usd_pass_fg', usd_path=Path('/shots/shot.usd'), frames='1001-1010',
		pass_prim='/Render/pass_fg', settings_prims=['/Render/rs'],
		outputs=['/out/beauty.%04d.exr', '/out/depth.%04d.exr'],
		plugin_info={'override_--pass': 'True', '--pass': '/Render/pass_fg', '--usd-input': '/shots/shot.usd'})


def test_job_info(job: Job) -> None:
	info = deadline.job_info(job, batch_name='shot', comment='v1', chunk_size=5)

	assert info['Plugin'] == 'HuskStandalone'
	assert info['Name'] == 'shot.usd_pass_fg'
	assert info['BatchName'] == 'shot'
	assert info['ChunkSize'] == '5'
	assert info['OutputFilename1'] == '/out/depth.%04d.exr'
	assert 'BatchName' not in deadline.job_info(job)


def test_plugin_info_version_is_not_a_husk_argument(job: Job) -> None:
	info = deadline.plugin_info(job, houdini_version='21.0.440')

	assert info['ArgumentList'] == 'override_--pass;--pass;--usd-input'
	assert info['Version'] == '21.0.440'


def test_parse_environment() -> None:
	text = ' OCIO = //server/aces/config.ocio \n\nHOUDINI_PATH=//server/tools;&\nEMPTY=\n'

	assert deadline.parse_environment(text) == {
		'OCIO': '//server/aces/config.ocio', 'HOUDINI_PATH': '//server/tools;&', 'EMPTY': ''}
	with pytest.raises(ValueError, match='NO_VALUE'):
		deadline.parse_environment('A=1\nNO_VALUE')
	with pytest.raises(ValueError):
		deadline.parse_environment('=1')


def test_environment_in_job_info(job: Job) -> None:
	info = deadline.job_info(job, environment={'OCIO': '/aces.ocio', 'A': 'x=y'})

	assert info['EnvironmentKeyValue0'] == 'OCIO=/aces.ocio'
	assert info['EnvironmentKeyValue1'] == 'A=x=y'


@pytest.mark.parametrize(('rez', 'expected'), [
	('', {}),
	(' houdini-21.0 ocio_aces ', {'RezRequest': 'houdini-21.0 ocio_aces'}),
	('//server/ctx/shot010.RXT', {'RezContext': '//server/ctx/shot010.RXT'}),
])
def test_rez_in_plugin_info(job: Job, rez: str, expected: dict[str, str]) -> None:
	info = deadline.plugin_info(job, rez=rez)

	assert {key: value for key, value in info.items() if key.startswith('Rez')} == expected
	assert 'Rez' not in info['ArgumentList']


def test_write_info_file_is_utf16(tmp_path: Path) -> None:
	path = tmp_path / 'info.job'
	deadline.write_info_file(path, {'Name': 'shot_ü', 'Frames': '1-2'})

	assert path.read_bytes()[:2] == b'\xff\xfe'
	assert path.read_text(encoding='utf-16') == 'Name=shot_ü\nFrames=1-2\n'


def test_find_deadlinecommand_from_env(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
	executable = tmp_path / ('deadlinecommand.exe' if sys.platform == 'win32' else 'deadlinecommand')
	executable.touch()
	monkeypatch.setenv('DEADLINE_PATH', str(tmp_path))

	assert deadline.find_deadlinecommand() == executable


def test_find_deadlinecommand_missing(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
	monkeypatch.setenv('DEADLINE_PATH', str(tmp_path))
	monkeypatch.setenv('PATH', str(tmp_path))
	monkeypatch.setattr(deadline, 'MACOS_DEADLINE_PATH_FILE', tmp_path / 'none')

	with pytest.raises(deadline.DeadlineError):
		deadline.find_deadlinecommand()


@pytest.mark.skipif(sys.platform == 'win32', reason='fake deadlinecommand is a shell script')
@pytest.mark.parametrize(('script_output', 'success', 'job_id'), [
	('Result=Success\nJobID=abc123\n', True, 'abc123'),
	('Result=Failure\nError: bad plugin\n', False, ''),
])
def test_submit_job(tmp_path: Path, job: Job, script_output: str, success: bool, job_id: str) -> None:
	received = tmp_path / 'received.txt'
	command = tmp_path / 'deadlinecommand'
	command.write_text(
		'#!/bin/sh\n'
		f'iconv -f UTF-16 -t UTF-8 "$1" > "{received}"\n'
		f'printf "{script_output}"\n')
	command.chmod(command.stat().st_mode | stat.S_IEXEC)

	result = deadline.submit_job(job, command, batch_name='shot', houdini_version='21.0.440')

	assert (result.success, result.job_id) == (success, job_id)
	assert 'Name=shot.usd_pass_fg' in received.read_text()
