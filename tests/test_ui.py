'''
Smoke tests for the dialog outside Houdini. Requires the "ui" dependency group:
uv sync --group ui
'''
from __future__ import annotations

import os
from pathlib import Path

import pytest

os.environ.setdefault('QT_QPA_PLATFORM', 'offscreen')
QtWidgets = pytest.importorskip('PySide6.QtWidgets', exc_type=ImportError)

from husk_submitter import ui  # noqa: E402
from husk_submitter.deadline import SubmitResult  # noqa: E402
from husk_submitter.options import default_arguments  # noqa: E402


@pytest.fixture(scope='module')
def app() -> QtWidgets.QApplication:
	return QtWidgets.QApplication.instance() or QtWidgets.QApplication([])


@pytest.fixture
def dialog(app: QtWidgets.QApplication, shot_usd: Path) -> ui.SubmitterDialog:
	return ui.SubmitterDialog(usd_paths=[str(shot_usd)])


def test_default_batch_name() -> None:
	assert ui.default_batch_name(['/s/Scene_v005.FG.usd', '/s/Scene_v005.BG.usd']) == 'Scene_v005'
	assert ui.default_batch_name([]) == ''


def test_defaults_match_option_definitions(dialog: ui.SubmitterDialog) -> None:
	options = dialog.job_options()
	expected = {key: value for key, value in default_arguments().items() if not key.endswith(ui.PER_JOB_FLAGS)}

	assert options.arguments == expected
	assert (options.pass_pattern, options.settings_pattern, options.output_override) == ('', '', '')
	assert options.frame_range is None
	assert dialog.batch_name.text() == 'shot_v001'


def test_edited_values(dialog: ui.SubmitterDialog) -> None:
	res = dialog.rows['--res']
	res.toggle.setChecked(True)
	res.editors[1].setValue(2048)
	dialog.rows['--disable-motionblur'].editors[0].setChecked(True)
	dialog.rows['--pass'].toggle.setChecked(True)
	dialog.rows['--pass'].editors[0].setText('pass_*')
	dialog.override_frames.setChecked(True)
	options = dialog.job_options()

	assert options.arguments['override_--res'] == 'True'
	assert options.arguments['--res'] == '2048 1080'
	assert options.arguments['--disable-motionblur'] == 'True'
	assert options.pass_pattern == 'pass_*'
	assert options.frame_range == (1001, 1250)
	assert dialog.start_frame.isEnabled()


def test_disabled_override_is_not_applied(dialog: ui.SubmitterDialog) -> None:
	dialog.rows['--output'].editors[0].setText('/o/x.exr')

	assert dialog.job_options().output_override == ''
	assert not dialog.rows['--output'].editors[0].isEnabled()


def test_submit_flow(dialog: ui.SubmitterDialog, monkeypatch: pytest.MonkeyPatch) -> None:
	submitted, shown = [], []
	monkeypatch.setattr(ui.JobPreviewDialog, 'exec', lambda self: QtWidgets.QDialog.Accepted)
	monkeypatch.setattr(ui, 'find_deadlinecommand', lambda: Path('deadlinecommand'))
	monkeypatch.setattr(ui, 'submit_job', lambda job, *a, **k: submitted.append(job) or SubmitResult(job, True, 'id', ''))
	monkeypatch.setattr(ui, 'show_results', lambda parent, results, failures: shown.append((results, failures)))
	dialog.rows['--pass'].toggle.setChecked(True)
	dialog.rows['--pass'].editors[0].setText('pass_*')

	dialog.submit()

	assert [job.name for job in submitted] == ['shot_v001.usda_pass_fg', 'shot_v001.usda_pass_bg']
	assert len(shown[0][0]) == 2 and shown[0][1] == {}


def test_preview_flags_collisions(app: QtWidgets.QApplication, shot_usd: Path) -> None:
	from husk_submitter.jobs import JobOptions, plan_jobs
	jobs, _ = plan_jobs([shot_usd], JobOptions(pass_pattern='pass_*', output_override='/o/{usd}.exr'))
	preview = ui.JobPreviewDialog(jobs, {'/missing.usd': "USD file doesn't exist"})
	table = preview.findChild(QtWidgets.QTableWidget)

	assert table.rowCount() == 2
	assert table.item(0, 2).foreground().color() == ui.COLLISION_COLOR
	assert any('Skipped /missing.usd' in label.text() for label in preview.findChildren(QtWidgets.QLabel))
