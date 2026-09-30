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
from PySide6 import QtCore  # noqa: E402

from husk_submitter import ui  # noqa: E402
from husk_submitter.deadline import SubmitResult  # noqa: E402
from husk_submitter.options import default_arguments  # noqa: E402


@pytest.fixture(scope='module')
def app() -> QtWidgets.QApplication:
	return QtWidgets.QApplication.instance() or QtWidgets.QApplication([])


@pytest.fixture(autouse=True)
def isolated_settings(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
	'''Keep the tests from reading or writing the user's remembered values.'''
	settings_path = str(tmp_path / 'settings.ini')
	monkeypatch.setattr(ui, 'user_settings', lambda: QtCore.QSettings(settings_path, QtCore.QSettings.IniFormat))
	monkeypatch.delenv(ui.REZ_REQUEST_VARIABLE, raising=False)


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
	monkeypatch.setattr(ui, 'submit_job', lambda job, *a, **k: submitted.append((job, k)) or SubmitResult(job, True, 'id', ''))
	monkeypatch.setattr(ui, 'show_results', lambda parent, results, failures: shown.append((results, failures)))
	dialog.rows['--pass'].toggle.setChecked(True)
	dialog.rows['--pass'].editors[0].setText('pass_*')
	dialog.version.setCurrentText('22.0')

	dialog.submit()

	assert [job.name for job, _ in submitted] == ['shot_v001.usda_pass_fg', 'shot_v001.usda_pass_bg']
	assert {kwargs['houdini_version'] for _, kwargs in submitted} == {'22.0'}
	assert len(shown[0][0]) == 2 and shown[0][1] == {}


@pytest.fixture
def other_usd(dialog: ui.SubmitterDialog, shot_usd: Path, tmp_path: Path) -> Path:
	other = tmp_path / 'other.usda'
	other.write_text(shot_usd.read_text())
	dialog.add_usd_paths([str(other)])
	return other


def test_file_overrides(dialog: ui.SubmitterDialog, other_usd: Path, monkeypatch: pytest.MonkeyPatch) -> None:
	panel = dialog.file_panel
	assert not panel.isEnabled()
	dialog.usd_table.selectRow(1)

	assert panel.title() == 'File Overrides: other.usda'
	assert [panel.settings_prims.itemText(i) for i in range(panel.settings_prims.count())] == ['*', '/Render/rs_beauty', '/Render/rs_util']
	assert [panel.camera.itemText(i) for i in range(panel.camera.count())] == ['/cameras/main', '/cameras/closeup']
	for key in ui.FILE_OVERRIDE_LABELS:
		panel.toggles[key].setChecked(True)
	panel.start_frame.setValue(1)
	panel.end_frame.setValue(5)
	panel.renderer.setCurrentText('BRAY_HdKarma')
	panel.settings_prims.setCurrentText('rs_util')
	panel.camera.setCurrentText('/cameras/closeup')
	panel.res_x.setValue(2048)
	panel.output.setText('/other/{settings}.$F4.exr')
	submitted = []
	monkeypatch.setattr(ui.JobPreviewDialog, 'exec', lambda self: QtWidgets.QDialog.Accepted)
	monkeypatch.setattr(ui, 'find_deadlinecommand', lambda: Path('deadlinecommand'))
	monkeypatch.setattr(ui, 'submit_job', lambda job, *a, **k: submitted.append(job) or SubmitResult(job, True, 'id', ''))
	monkeypatch.setattr(ui, 'show_results', lambda *args: None)

	dialog.submit()

	assert dialog.usd_table.item(0, 1).text() == ''
	assert dialog.usd_table.item(1, 1).text() == 'Frame Range, Renderer, Settings, Camera, Resolution, Output/s'
	shot_job, other_job = submitted
	assert (shot_job.frames, shot_job.plugin_info['override_--camera']) == ('1001-1010', 'False')
	assert other_job.frames == '1-5'
	assert other_job.outputs == ['/other/rs_util.$F4.exr']
	assert other_job.plugin_info['--renderer'] == 'BRAY_HdKarma'
	assert (other_job.plugin_info['override_--camera'], other_job.plugin_info['--camera']) == ('True', '/cameras/closeup')
	assert (other_job.plugin_info['override_--res'], other_job.plugin_info['--res']) == ('True', '2048 1080')


def test_file_overrides_on_several_files(dialog: ui.SubmitterDialog, other_usd: Path, shot_usd: Path) -> None:
	panel = dialog.file_panel
	dialog.usd_table.selectRow(0)
	panel.toggles['--camera'].setChecked(True)
	panel.camera.setCurrentText('/cameras/closeup')
	dialog.usd_table.selectRow(1)
	panel.toggles['--output'].setChecked(True)  # blank, so the shared Output/s is used
	assert not panel.toggles['--camera'].isChecked()

	dialog.usd_table.selectAll()
	assert panel.title() == 'File Overrides: 2 files'
	assert panel.camera.currentText() == '/cameras/closeup'
	panel.toggles['frames'].setChecked(True)
	panel.end_frame.setValue(1100)

	assert dialog.file_overrides == {
		str(shot_usd): {'--camera': '/cameras/closeup', 'frames': (1001, 1100)},
		str(other_usd): {'--output': '', 'frames': (1001, 1100)}}
	assert dialog.file_job_options()[other_usd].output_override == ''

	dialog.usd_table.selectRow(0)
	dialog._remove_selected()
	assert list(dialog.file_overrides) == [str(other_usd)]
	dialog._clear_usd()
	assert dialog.file_overrides == {}
	assert not panel.isEnabled()


def test_environment_and_rez_are_submitted_and_remembered(dialog: ui.SubmitterDialog, shot_usd: Path, monkeypatch: pytest.MonkeyPatch) -> None:
	submitted = []
	monkeypatch.setattr(ui.JobPreviewDialog, 'exec', lambda self: QtWidgets.QDialog.Accepted)
	monkeypatch.setattr(ui, 'find_deadlinecommand', lambda: Path('deadlinecommand'))
	monkeypatch.setattr(ui, 'submit_job', lambda job, *a, **k: submitted.append(k) or SubmitResult(job, True, 'id', ''))
	monkeypatch.setattr(ui, 'show_results', lambda *args: None)
	dialog.rez.setText('houdini-21.0 ocio_aces')
	dialog.environment.setPlainText('OCIO=/aces.ocio\n\nSTUDIO=tw\n')

	dialog.submit()

	assert submitted[0]['environment'] == {'OCIO': '/aces.ocio', 'STUDIO': 'tw'}
	assert submitted[0]['rez'] == 'houdini-21.0 ocio_aces'
	reopened = ui.SubmitterDialog(usd_paths=[str(shot_usd)])
	assert reopened.rez.text() == 'houdini-21.0 ocio_aces'
	assert reopened.environment.toPlainText() == 'OCIO=/aces.ocio\n\nSTUDIO=tw\n'


def test_invalid_environment_is_not_submitted(dialog: ui.SubmitterDialog, monkeypatch: pytest.MonkeyPatch) -> None:
	warnings = []
	monkeypatch.setattr(QtWidgets.QMessageBox, 'warning', lambda parent, title, text: warnings.append(text))
	monkeypatch.setattr(ui, 'plan_jobs', lambda *args: pytest.fail('jobs planned with an invalid environment'))
	dialog.environment.setPlainText('OCIO')

	dialog.submit()

	assert 'OCIO' in warnings[0]


def test_rez_defaults_to_the_current_context(app: QtWidgets.QApplication, monkeypatch: pytest.MonkeyPatch) -> None:
	ui.user_settings().setValue('rez', 'remembered')
	monkeypatch.setenv(ui.REZ_REQUEST_VARIABLE, 'houdini-21.0 studio_tools')

	assert ui.SubmitterDialog().rez.text() == 'houdini-21.0 studio_tools'


def test_running_houdini_version_is_used(app: QtWidgets.QApplication, monkeypatch: pytest.MonkeyPatch) -> None:
	monkeypatch.setattr(ui, 'houdini_version', lambda: '21.0.729')
	dialog = ui.SubmitterDialog()
	submitted = []
	monkeypatch.setattr(ui, 'submit_job', lambda job, *a, **k: submitted.append(k) or SubmitResult(job, True, 'id', ''))

	dialog._submit_one(None, Path('deadlinecommand'))

	assert dialog.version is None
	assert submitted[0]['houdini_version'] == '21.0.729'


def test_preview_flags_collisions(app: QtWidgets.QApplication, shot_usd: Path) -> None:
	from husk_submitter.jobs import JobOptions, plan_jobs
	jobs, _ = plan_jobs([shot_usd], JobOptions(pass_pattern='pass_*', output_override='/o/{usd}.exr'))
	preview = ui.JobPreviewDialog(jobs, {'/missing.usd': "USD file doesn't exist"})
	table = preview.findChild(QtWidgets.QTableWidget)

	assert table.rowCount() == 2
	assert table.item(0, 2).foreground().color() == ui.COLLISION_COLOR
	assert any('Skipped /missing.usd' in label.text() for label in preview.findChildren(QtWidgets.QLabel))


def test_preview_edits_outputs_per_job(app: QtWidgets.QApplication, shot_usd: Path) -> None:
	from husk_submitter.jobs import JobOptions, plan_jobs
	jobs, _ = plan_jobs([shot_usd], JobOptions(pass_pattern='pass_*', output_override='/o/{usd}.exr'))
	preview = ui.JobPreviewDialog(jobs, {})
	assert not preview.collision_label.isHidden()

	preview.table.item(1, ui.OUTPUTS_COLUMN).setText('/o/{pass}/beauty.$F4.exr, /o/{pass}/depth.$F4.exr')

	assert jobs[1].outputs == ['/o/pass_bg/beauty.$F4.exr', '/o/pass_bg/depth.$F4.exr']
	assert jobs[1].plugin_info['--output'] == '/o/pass_bg/beauty.$F4.exr,/o/pass_bg/depth.$F4.exr'
	assert jobs[0].outputs == ['/o/shot_v001.exr']
	assert preview.table.item(1, ui.OUTPUTS_COLUMN).text() == '/o/pass_bg/beauty.$F4.exr, /o/pass_bg/depth.$F4.exr'
	assert preview.table.item(0, ui.OUTPUTS_COLUMN).foreground().color() != ui.COLLISION_COLOR
	assert preview.collision_label.isHidden()
	assert not preview.table.item(0, 0).flags() & QtCore.Qt.ItemIsEditable
