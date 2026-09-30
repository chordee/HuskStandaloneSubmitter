'''
Turn a USD file's render prims and the submitter options into Deadline jobs.

Pass > Settings > Product > ProductName
A RenderPass drives its RenderSettings (renderSource), RenderSettings drive
their RenderProducts, and RenderProducts drive the output file names.
'''
from __future__ import annotations

import re
from collections import Counter
from dataclasses import dataclass, field
from fnmatch import fnmatchcase
from pathlib import Path
from typing import Iterable

from .render_info import RENDER_ROOT, RenderInfo, RenderInfoError, read_render_info

OUTPUT_TOKEN_PATTERN = re.compile(r'\{(usd|pass|settings)\}')
PRIM_PATTERN_SEPARATOR = re.compile(r'[,\s]+')


class SubmissionError(Exception):
	'''Raised when the options cannot be resolved against a USD file.'''


@dataclass
class JobOptions:
	'''
	Submitter options shared by every job.

	arguments: husk plugin info entries (see options.OPTIONS), excluding
	--pass, --settings, --output and --usd-input which are set per job.
	Empty patterns mean the corresponding override is disabled.
	'''
	arguments: dict[str, str] = field(default_factory=dict)
	pass_pattern: str = ''
	settings_pattern: str = ''
	output_override: str = ''
	separate_jobs: bool = False
	frame_range: tuple[int, int] | None = None
	render_root: str = RENDER_ROOT


@dataclass
class Job:
	name: str
	usd_path: Path
	frames: str
	pass_prim: str
	settings_prims: list[str]
	outputs: list[str]
	plugin_info: dict[str, str]


def match_prims(patterns: str, candidates: Iterable[str], render_root: str = RENDER_ROOT) -> list[str]:
	'''
	Resolve a comma or space separated list of prim patterns.

	Absolute patterns match full prim paths, relative patterns match the path
	below render_root or the prim name. * matches any characters.
	'''
	candidates = list(candidates)
	matched: list[str] = []
	for pattern in filter(None, PRIM_PATTERN_SEPARATOR.split(patterns)):
		hits = [path for path in candidates if _prim_matches(path, pattern, render_root)]
		if not hits:
			available = ', '.join(candidates) or 'none'
			raise SubmissionError(f'{pattern!r} matches no prims (available: {available})')
		matched += [hit for hit in hits if hit not in matched]
	return matched


def _prim_matches(path: str, pattern: str, render_root: str) -> bool:
	if pattern.startswith('/'):
		return fnmatchcase(path, pattern)
	relative = path.removeprefix(render_root.rstrip('/') + '/')
	return fnmatchcase(relative, pattern) or fnmatchcase(path.rsplit('/', 1)[-1], pattern)


def determine_outputs(info: RenderInfo, options: JobOptions) -> dict[str, dict[str, list[str]]]:
	'''
	Map each pass to its settings prims and each settings prim to its outputs.
	A pass of '' means no pass is used.

	eg. {'/Render/pass1': {'/Render/settings1': ['/out/beauty.%04d.exr']}}
	'''
	pass_prims = match_prims(options.pass_pattern, info.passes, options.render_root) if options.pass_pattern else ['']
	settings_override = match_prims(options.settings_pattern, info.settings, options.render_root) if options.settings_pattern else []
	outputs_override = [path.strip() for path in options.output_override.split(',') if path.strip()]

	result = {}
	for pass_prim in pass_prims:
		settings_prims = settings_override or [_default_settings(info, pass_prim)]
		result[pass_prim] = {
			settings_prim: outputs_override or _product_names(info, settings_prim)
			for settings_prim in settings_prims}
	return result


def _default_settings(info: RenderInfo, pass_prim: str) -> str:
	'''
	The pass's renderSource, else the stage's renderSettingsPrimPath,
	else the only RenderSettings prim on the stage.
	'''
	settings = info.passes.get(pass_prim, '') or info.default_settings
	if not settings and len(info.settings) == 1:
		settings = next(iter(info.settings))
	if settings not in info.settings:
		raise SubmissionError(
			f'Cannot determine the RenderSettings prim for {pass_prim or "the stage"} '
			f'in {info.path}; enable the Settings override.')
	return settings


def _product_names(info: RenderInfo, settings_prim: str) -> list[str]:
	return [info.products[product] for product in info.settings[settings_prim] if product in info.products]


def group_prim_submissions(
		outputs: dict[str, dict[str, list[str]]],
		separate_jobs: bool) -> list[tuple[str, list[str], list[str]]]:
	'''
	Group outputs into (pass, settings prims, outputs) per job:
	one job per pass, or per pass and settings prim when separate_jobs is set.
	'''
	submissions = []
	for pass_prim, settings_outputs in outputs.items():
		if separate_jobs:
			submissions += [(pass_prim, [settings], names) for settings, names in settings_outputs.items()]
			continue
		# Dedupe while preserving order, as --output maps to products by position
		names = list(dict.fromkeys(name for names in settings_outputs.values() for name in names))
		submissions.append((pass_prim, list(settings_outputs), names))
	return submissions


def expand_output_tokens(path: str, usd_path: Path, pass_prim: str, settings_prims: list[str]) -> str:
	'''
	Expand {usd}, {pass} and {settings} in an output path.
	Husk variables such as $F4 and <F4> are left for husk to expand.
	{settings} uses the first settings prim when a job renders multiple.
	'''
	tokens = {
		'usd': usd_path.stem,
		'pass': _prim_name(pass_prim),
		'settings': _prim_name(settings_prims[0]) if settings_prims else '',
	}
	expanded = OUTPUT_TOKEN_PATTERN.sub(lambda match: tokens[match.group(1)], path)
	# Collapse separators doubled by empty tokens, keeping a leading UNC prefix
	return re.sub(r'(?<=.)[\\/]{2,}', '/', expanded)


def set_outputs(job: Job, outputs: str) -> None:
	'''
	Replace a job's outputs with a comma separated list of paths,
	expanding {usd}, {pass} and {settings}.
	'''
	job.outputs = [
		expand_output_tokens(path.strip(), job.usd_path, job.pass_prim, job.settings_prims)
		for path in outputs.split(',') if path.strip()]
	job.plugin_info['--output'] = ','.join(job.outputs)


def _prim_name(prim_path: str) -> str:
	return prim_path.rsplit('/', 1)[-1]


def build_jobs(info: RenderInfo, options: JobOptions) -> list[Job]:
	'''
	Build the jobs for one USD file. Job names are made unique across
	files by assign_unique_names once all files are processed.
	'''
	start, end = options.frame_range or (info.start_frame, info.end_frame)
	outputs = determine_outputs(info, options)

	jobs = []
	for pass_prim, settings_prims, names in group_prim_submissions(outputs, options.separate_jobs):
		names = [expand_output_tokens(name, info.path, pass_prim, settings_prims) for name in names]
		jobs.append(Job(
			name='',
			usd_path=info.path,
			frames=f'{start}-{end}',
			pass_prim=pass_prim,
			settings_prims=settings_prims,
			outputs=names,
			plugin_info=_plugin_info(options, info.path, pass_prim, settings_prims, names)))
	return jobs


def _plugin_info(
		options: JobOptions, usd_path: Path, pass_prim: str,
		settings_prims: list[str], outputs: list[str]) -> dict[str, str]:
	plugin_info = dict(options.arguments)
	plugin_info.update({
		'override_--pass': str(bool(pass_prim)),
		'--pass': pass_prim,
		'override_--settings': 'True',
		'--settings': ','.join(settings_prims),
		'override_--output': 'True',
		'--output': ','.join(outputs),
		'--usd-input': str(usd_path),
	})
	return plugin_info


def assign_unique_names(jobs: list[Job], separate_jobs: bool, render_root: str = RENDER_ROOT) -> None:
	'''
	Name jobs <usd file>_<pass>[_<settings>] using prim names. Jobs that would
	share a name use prim paths relative to render_root instead, and any names
	still shared get a numeric suffix.
	'''
	for job in jobs:
		job.name = _job_name(job, separate_jobs, None)
	for job in _shared_name_jobs(jobs):
		job.name = _job_name(job, separate_jobs, render_root)

	seen: Counter[str] = Counter()
	totals = Counter(job.name for job in jobs)
	for job in jobs:
		if totals[job.name] > 1:
			seen[job.name] += 1
			job.name = f'{job.name} ({seen[job.name]})'


def _shared_name_jobs(jobs: list[Job]) -> list[Job]:
	counts = Counter(job.name for job in jobs)
	return [job for job in jobs if counts[job.name] > 1]


def _job_name(job: Job, separate_jobs: bool, render_root: str | None) -> str:
	'''
	render_root None labels prims by name, otherwise by path below render_root.
	'''
	def label(prim_path: str) -> str:
		if render_root is None:
			return _prim_name(prim_path)
		return prim_path.removeprefix(render_root.rstrip('/') + '/').strip('/').replace('/', '_')

	name = job.usd_path.name
	if job.pass_prim:
		name += '_' + label(job.pass_prim)
	if separate_jobs:
		name += '_' + label(job.settings_prims[0])
	return name


def find_output_collisions(jobs: list[Job]) -> list[str]:
	'''
	Output paths written by more than one job.
	'''
	counts = Counter(output for job in jobs for output in set(job.outputs))
	return [output for output, count in counts.items() if count > 1]


def plan_jobs(
		usd_paths: Iterable[Path], options: JobOptions,
		file_options: dict[Path, JobOptions] | None = None) -> tuple[list[Job], dict[str, str]]:
	'''
	Build uniquely named jobs for every USD file.
	file_options replaces options for the given files.
	Returns the jobs and a mapping of USD path -> error for files that failed.
	'''
	file_options = file_options or {}
	jobs: list[Job] = []
	failures: dict[str, str] = {}
	for usd_path in usd_paths:
		if not usd_path.is_file():
			failures[str(usd_path)] = "USD file doesn't exist"
			continue
		try:
			jobs += build_jobs(read_render_info(usd_path, options.render_root), file_options.get(usd_path, options))
		except (RenderInfoError, SubmissionError) as error:
			failures[str(usd_path)] = str(error)

	assign_unique_names(jobs, options.separate_jobs, options.render_root)
	return jobs, failures
