from __future__ import annotations

from pathlib import Path

import pytest

from conftest import make_stage
from husk_submitter.jobs import (
	JobOptions, SubmissionError, determine_outputs, expand_output_tokens,
	find_output_collisions, group_prim_submissions, match_prims, plan_jobs)
from husk_submitter.render_info import read_render_info

PRIMS = ['/Render/pass_fg', '/Render/pass_bg', '/Render/sub/pass_fg2', '/Render/final']


@pytest.mark.parametrize(('pattern', 'expected'), [
	('pass_fg', ['/Render/pass_fg']),
	('pass_*', ['/Render/pass_fg', '/Render/pass_bg', '/Render/sub/pass_fg2']),
	('sub/*', ['/Render/sub/pass_fg2']),
	('/Render/final', ['/Render/final']),
	('final, pass_bg pass_bg', ['/Render/final', '/Render/pass_bg']),
])
def test_match_prims(pattern: str, expected: list[str]) -> None:
	assert match_prims(pattern, PRIMS) == expected


def test_match_prims_is_not_a_substring_search() -> None:
	with pytest.raises(SubmissionError, match='matches no prims'):
		match_prims('pass', PRIMS)


def test_default_outputs(shot_usd: Path) -> None:
	outputs = determine_outputs(read_render_info(shot_usd), JobOptions())

	assert outputs == {'': {'/Render/rs_beauty': ['/out/beauty.%04d.exr', '/out/depth.%04d.exr']}}


def test_pass_uses_render_source(shot_usd: Path) -> None:
	outputs = determine_outputs(read_render_info(shot_usd), JobOptions(pass_pattern='pass_*'))

	assert list(outputs) == ['/Render/pass_fg', '/Render/pass_bg']
	assert all(list(settings) == ['/Render/rs_beauty'] for settings in outputs.values())


def test_output_override_applies_to_every_settings(shot_usd: Path) -> None:
	options = JobOptions(settings_pattern='rs_*', output_override='/o/a.$F4.exr, /o/b.$F4.exr')
	outputs = determine_outputs(read_render_info(shot_usd), options)

	assert outputs == {'': {
		'/Render/rs_beauty': ['/o/a.$F4.exr', '/o/b.$F4.exr'],
		'/Render/rs_util': ['/o/a.$F4.exr', '/o/b.$F4.exr']}}


def test_unknown_default_settings(tmp_path: Path) -> None:
	path = make_stage(tmp_path / 'x.usda', products={}, settings={'/Render/a': [], '/Render/b': []})

	with pytest.raises(SubmissionError, match='enable the Settings override'):
		determine_outputs(read_render_info(path), JobOptions())


def test_group_preserves_output_order() -> None:
	outputs = {'': {'/R/a': ['/o/z', '/o/a'], '/R/b': ['/o/a', '/o/m']}}

	assert group_prim_submissions(outputs, separate_jobs=False) == [('', ['/R/a', '/R/b'], ['/o/z', '/o/a', '/o/m'])]
	assert group_prim_submissions(outputs, separate_jobs=True) == [
		('', ['/R/a'], ['/o/z', '/o/a']), ('', ['/R/b'], ['/o/a', '/o/m'])]


@pytest.mark.parametrize(('path', 'pass_prim', 'expected'), [
	('/o/{usd}/{pass}/{settings}.<F4>.exr', '/Render/fg', '/o/shot_v001/fg/rs.<F4>.exr'),
	('/o/{usd}/{pass}/{settings}.$F4.exr', '', '/o/shot_v001/rs.$F4.exr'),
	('//srv/{pass}/x.exr', '', '//srv/x.exr'),
	('/o/{unknown}.exr', '', '/o/{unknown}.exr'),
])
def test_expand_output_tokens(path: str, pass_prim: str, expected: str) -> None:
	assert expand_output_tokens(path, Path('/shots/shot_v001.usd'), pass_prim, ['/Render/rs']) == expected


def test_plan_jobs(shot_usd: Path) -> None:
	options = JobOptions(arguments={'--renderer': 'BRAY_HdKarmaXPU'}, pass_pattern='pass_*', frame_range=(1, 5))
	jobs, failures = plan_jobs([shot_usd], options)

	assert failures == {}
	assert [job.name for job in jobs] == ['shot_v001.usda_pass_fg', 'shot_v001.usda_pass_bg']
	job = jobs[0]
	assert job.frames == '1-5'
	assert job.plugin_info['--renderer'] == 'BRAY_HdKarmaXPU'
	assert job.plugin_info['--pass'] == '/Render/pass_fg'
	assert job.plugin_info['--settings'] == '/Render/rs_beauty'
	assert job.plugin_info['--output'] == '/out/beauty.%04d.exr,/out/depth.%04d.exr'
	assert job.plugin_info['--usd-input'] == str(shot_usd)


def test_plan_jobs_without_pass_disables_pass_override(shot_usd: Path) -> None:
	jobs, _ = plan_jobs([shot_usd], JobOptions())

	assert jobs[0].name == 'shot_v001.usda'
	assert jobs[0].plugin_info['override_--pass'] == 'False'
	assert jobs[0].frames == '1001-1010'


def test_job_names_unique_for_same_named_settings(tmp_path: Path) -> None:
	'''Issue #2: settings prims sharing a name under different parents.'''
	path = make_stage(
		tmp_path / 'shot.usda', products={},
		settings={'/Render/a/preview': [], '/Render/b/preview': [], '/Render/final': []})
	jobs, _ = plan_jobs([path], JobOptions(settings_pattern='*', separate_jobs=True))

	assert [job.name for job in jobs] == ['shot.usda_a_preview', 'shot.usda_b_preview', 'shot.usda_final']


def test_job_names_unique_for_same_named_files(tmp_path: Path) -> None:
	paths = []
	for directory in ('a', 'b'):
		(tmp_path / directory).mkdir()
		paths.append(make_stage(tmp_path / directory / 'shot.usda', products={}, settings={'/Render/rs': []}))
	jobs, _ = plan_jobs(paths, JobOptions())

	assert [job.name for job in jobs] == ['shot.usda (1)', 'shot.usda (2)']


def test_plan_jobs_records_failures(shot_usd: Path, tmp_path: Path) -> None:
	missing = tmp_path / 'missing.usda'
	jobs, failures = plan_jobs([missing, shot_usd], JobOptions(pass_pattern='nope'))

	assert jobs == []
	assert failures[str(missing)] == "USD file doesn't exist"
	assert 'matches no prims' in failures[str(shot_usd)]


def test_output_collisions(shot_usd: Path) -> None:
	shared = JobOptions(pass_pattern='pass_*', output_override='/o/{usd}.$F4.exr')
	unique = JobOptions(pass_pattern='pass_*', output_override='/o/{usd}_{pass}.$F4.exr')

	assert find_output_collisions(plan_jobs([shot_usd], shared)[0]) == ['/o/shot_v001.$F4.exr']
	assert find_output_collisions(plan_jobs([shot_usd], unique)[0]) == []
