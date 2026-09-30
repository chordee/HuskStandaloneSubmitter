'''
PySide6 submitter dialog for Houdini 21+.

In Houdini: from husk_submitter import ui; ui.show()
Standalone (usd-core + PySide6): python -m husk_submitter.ui [usd files]
'''
from __future__ import annotations

import logging
import os
import sys
from dataclasses import replace
from pathlib import Path

from PySide6 import QtCore, QtGui, QtWidgets

from .deadline import DeadlineError, SubmitResult, find_deadlinecommand, parse_environment, submit_job
from .jobs import Job, JobOptions, find_output_collisions, plan_jobs, set_outputs
from .options import GROUPS, HOUDINI_VERSIONS, OPTIONS, USD_FILE_FILTER, HuskOption, Kind
from .render_info import RenderInfoError, read_cameras, read_render_info

logger = logging.getLogger(__name__)

WINDOW_TITLE = 'Husk Deadline Submitter'
PER_JOB_FLAGS = ('--pass', '--settings', '--output')
COLLISION_COLOR = QtGui.QColor('#e06c6c')
REZ_REQUEST_VARIABLE = 'REZ_USED_REQUEST'
FILE_OVERRIDE_LABELS = {
	'frames': 'Frame Range', '--renderer': 'Renderer', '--settings': 'Settings',
	'--camera': 'Camera', '--res': 'Resolution', '--output': 'Output/s'}
FILE_OVERRIDE_TOOLTIPS = {
	'--settings': (
		'RenderSettings prim/s of the file, replacing the shared Settings Prim/s.\n'
		'Comma or space separated list and/or * wildcards.'),
	'--camera': (
		'Camera prim of the file.\n'
		'Cameras inside payloads are not listed, type their path instead.'),
	'--output': (
		'Output/s of the file, replacing the shared Output/s.\n'
		'Comma separated, one path per RenderProduct in order.\n'
		'{usd}, {pass} and {settings} are expanded per job.'),
}
OUTPUTS_COLUMN = 2
OUTPUTS_TOOLTIP = (
	'Double-click to edit. Comma separated, one path per RenderProduct in order.\n'
	'{usd}, {pass} and {settings} are expanded for the job.')
FRAME_LIMIT = 65535

_dialog: SubmitterDialog | None = None  # keeps the non-modal dialog alive


def houdini_version() -> str:
	try:
		import hou
	except ImportError:
		return ''
	return hou.applicationVersionString()


def user_settings() -> QtCore.QSettings:
	'''
	Values remembered between sessions, such as the last directory, rez and environment.
	'''
	return QtCore.QSettings('HuskStandaloneSubmitter', 'HoudiniSubmitter')


def default_batch_name(paths: list[str]) -> str:
	'''
	Shortest common prefix of the input files.
	eg. Scene_v005.FG.usd;Scene_v005.BG.usd -> Scene_v005
	'''
	common = os.path.commonprefix(paths)
	return os.path.basename(os.path.splitext(common)[0]) if common else ''


class OptionRow:
	'''
	Editor widgets for one HuskOption, with an enable toggle when the option has one.
	'''

	def __init__(self, option: HuskOption) -> None:
		self.option = option
		self.toggle: QtWidgets.QCheckBox | None = None
		self.editors = self._create_editors()
		self.widget = QtWidgets.QWidget()
		layout = QtWidgets.QHBoxLayout(self.widget)
		layout.setContentsMargins(0, 0, 0, 0)

		if option.override is not None:
			self.toggle = QtWidgets.QCheckBox()
			self.toggle.setChecked(option.override)
			self.toggle.setToolTip(f'Enable {option.flag}')
			self.toggle.toggled.connect(self._sync_enabled)
			layout.addWidget(self.toggle)
		for editor in self.editors:
			editor.setToolTip(option.tooltip)
			layout.addWidget(editor, 0 if isinstance(editor, (QtWidgets.QLabel, QtWidgets.QPushButton)) else 1)
		self._sync_enabled()

	@property
	def label(self) -> str:
		return '' if self.option.kind is Kind.BOOL else self.option.label

	def _create_editors(self) -> list[QtWidgets.QWidget]:
		option = self.option
		if option.kind is Kind.INT:
			return [self._spin_box(option.default)]
		if option.kind is Kind.INT2:
			x_label, y_label = option.component_labels
			return [
				QtWidgets.QLabel(x_label), self._spin_box(option.default[0]),
				QtWidgets.QLabel(y_label), self._spin_box(option.default[1])]
		if option.kind is Kind.ENUM:
			combo = QtWidgets.QComboBox()
			combo.addItems(option.choices)
			combo.setCurrentText(option.default)
			return [combo]
		if option.kind is Kind.BOOL:
			checkbox = QtWidgets.QCheckBox(option.label)
			checkbox.setChecked(option.default)
			return [checkbox]

		line_edit = QtWidgets.QLineEdit(option.default)
		if option.kind is not Kind.FILE_SAVE:
			return [line_edit]
		browse = QtWidgets.QPushButton('...')
		browse.clicked.connect(lambda: self._browse_output(line_edit))
		return [line_edit, browse]

	def _spin_box(self, value: int) -> QtWidgets.QSpinBox:
		spin_box = QtWidgets.QSpinBox()
		spin_box.setRange(self.option.minimum, self.option.maximum)
		spin_box.setValue(value)
		return spin_box

	def _browse_output(self, line_edit: QtWidgets.QLineEdit) -> None:
		path, _ = QtWidgets.QFileDialog.getSaveFileName(self.widget, 'Output image', line_edit.text())
		if path:
			line_edit.setText(path)

	def _sync_enabled(self) -> None:
		for editor in self.editors:
			editor.setEnabled(self.enabled())

	def enabled(self) -> bool:
		return self.toggle is None or self.toggle.isChecked()

	def value(self) -> str:
		editors = [editor for editor in self.editors if not isinstance(editor, (QtWidgets.QLabel, QtWidgets.QPushButton))]
		values = []
		for editor in editors:
			if isinstance(editor, QtWidgets.QSpinBox):
				values.append(editor.value())
			elif isinstance(editor, QtWidgets.QComboBox):
				values.append(editor.currentText())
			elif isinstance(editor, QtWidgets.QCheckBox):
				values.append(editor.isChecked())
			else:
				values.append(editor.text().strip())
		return self.option.format_value(tuple(values) if len(values) > 1 else values[0])

	def arguments(self) -> dict[str, str]:
		'''
		Plugin info entries for this option.
		'''
		arguments = {self.option.flag: self.value()}
		if self.toggle is not None:
			arguments = {self.option.override_key: str(self.toggle.isChecked()), **arguments}
		return arguments


class FileOverridesPanel(QtWidgets.QGroupBox):
	'''
	Overrides of the shared settings for the USD files selected in the file list.
	Shows the first selected file. A changed row is applied to every selected
	file, other rows keep each file's own overrides.
	'''
	changed = QtCore.Signal()

	def __init__(self, dialog: SubmitterDialog) -> None:
		super().__init__('File Overrides')
		self.dialog = dialog
		self.paths: list[str] = []
		self.toggles: dict[str, QtWidgets.QCheckBox] = {}
		self.editors: dict[str, list[QtWidgets.QWidget]] = {}
		self._loading = False

		self.start_frame, self.end_frame = self._spin_box(-FRAME_LIMIT), self._spin_box(-FRAME_LIMIT)
		self.renderer = QtWidgets.QComboBox()
		self.renderer.addItems(dialog.rows['--renderer'].option.choices)
		self.settings_prims, self.camera = self._prim_combo(), self._prim_combo()
		self.res_x, self.res_y = self._spin_box(0), self._spin_box(0)
		self.output = QtWidgets.QLineEdit()

		form = QtWidgets.QFormLayout(self)
		for key, editors in (
				('frames', [QtWidgets.QLabel('Start'), self.start_frame, QtWidgets.QLabel('End'), self.end_frame]),
				('--renderer', [self.renderer]),
				('--settings', [self.settings_prims]),
				('--camera', [self.camera]),
				('--res', [QtWidgets.QLabel('x'), self.res_x, QtWidgets.QLabel('y'), self.res_y]),
				('--output', [self.output])):
			form.addRow(FILE_OVERRIDE_LABELS[key], self._row(key, editors))
		self.set_paths([])

	@staticmethod
	def _spin_box(minimum: int) -> QtWidgets.QSpinBox:
		spin_box = QtWidgets.QSpinBox()
		spin_box.setRange(minimum, FRAME_LIMIT)
		return spin_box

	@staticmethod
	def _prim_combo() -> QtWidgets.QComboBox:
		combo = QtWidgets.QComboBox()
		combo.setEditable(True)
		combo.setInsertPolicy(QtWidgets.QComboBox.NoInsert)
		return combo

	def _row(self, key: str, editors: list[QtWidgets.QWidget]) -> QtWidgets.QWidget:
		widget = QtWidgets.QWidget()
		layout = QtWidgets.QHBoxLayout(widget)
		layout.setContentsMargins(0, 0, 0, 0)
		toggle = QtWidgets.QCheckBox()
		toggle.setToolTip(f'Override {FILE_OVERRIDE_LABELS[key]} for the selected files')
		toggle.toggled.connect(lambda: self._row_changed(key))
		layout.addWidget(toggle)
		signals = {QtWidgets.QSpinBox: 'valueChanged', QtWidgets.QComboBox: 'currentTextChanged', QtWidgets.QLineEdit: 'textChanged'}
		for editor in editors:
			editor.setToolTip(FILE_OVERRIDE_TOOLTIPS.get(key, ''))
			layout.addWidget(editor, 0 if isinstance(editor, QtWidgets.QLabel) else 1)
			if type(editor) in signals:
				getattr(editor, signals[type(editor)]).connect(lambda *_: self._row_changed(key))
		self.toggles[key], self.editors[key] = toggle, editors
		return widget

	def set_paths(self, paths: list[str]) -> None:
		self.paths = paths
		self.setEnabled(bool(paths))
		if len(paths) > 1:
			self.setTitle(f'File Overrides: {len(paths)} files')
		else:
			self.setTitle('File Overrides' + (f': {os.path.basename(paths[0])}' if paths else ''))

		settings, cameras = [], []
		for path in paths:
			file_settings, file_cameras = self.dialog.prim_choices(path)
			settings += [prim for prim in file_settings if prim not in settings]
			cameras += [prim for prim in file_cameras if prim not in cameras]
		overrides = self.dialog.file_overrides.get(paths[0], {}) if paths else {}

		self._loading = True
		for combo, items in ((self.settings_prims, ['*', *settings] if settings else []), (self.camera, cameras)):
			combo.clear()
			combo.addItems(items)
		for key, toggle in self.toggles.items():
			toggle.setChecked(key in overrides)
			if paths:
				self._set_value(key, overrides.get(key, self.dialog.shared_value(key)))
			self._row_changed(key)  # only syncs the editors' enabled state while loading
		self._loading = False

	def _value(self, key: str) -> str | tuple[int, int]:
		if key == 'frames':
			return self.start_frame.value(), self.end_frame.value()
		if key == '--res':
			return self.res_x.value(), self.res_y.value()
		if key == '--output':
			return self.output.text().strip()
		return {'--renderer': self.renderer, '--settings': self.settings_prims, '--camera': self.camera}[key].currentText().strip()

	def _set_value(self, key: str, value: str | tuple[int, int]) -> None:
		if key == 'frames':
			self.start_frame.setValue(value[0])
			self.end_frame.setValue(value[1])
		elif key == '--res':
			self.res_x.setValue(value[0])
			self.res_y.setValue(value[1])
		elif key == '--output':
			self.output.setText(value)
		else:
			{'--renderer': self.renderer, '--settings': self.settings_prims, '--camera': self.camera}[key].setCurrentText(value)

	def _row_changed(self, key: str) -> None:
		for editor in self.editors.get(key, []):
			editor.setEnabled(self.toggles[key].isChecked())
		if self._loading:
			return
		for path in self.paths:
			overrides = self.dialog.file_overrides.setdefault(path, {})
			if self.toggles[key].isChecked():
				overrides[key] = self._value(key)
			else:
				overrides.pop(key, None)
			if not overrides:
				del self.dialog.file_overrides[path]
		self.changed.emit()


class SubmitterDialog(QtWidgets.QDialog):
	def __init__(self, parent: QtWidgets.QWidget | None = None, usd_paths: list[str] | None = None) -> None:
		super().__init__(parent)
		self.setWindowTitle(WINDOW_TITLE)
		self.settings = user_settings()
		self.rows = {option.flag: OptionRow(option) for option in OPTIONS}
		self._batch_edited = False
		self.running_version = houdini_version()
		self.file_overrides: dict[str, dict[str, str | tuple[int, int]]] = {}
		self._prim_choices: dict[str, tuple[list[str], list[str]]] = {}

		layout = QtWidgets.QVBoxLayout(self)
		layout.addWidget(self._build_submission_group())
		for group in GROUPS[1:]:
			layout.addWidget(self._build_option_group(group))
		layout.addLayout(self._build_buttons())
		self.add_usd_paths(usd_paths or [])

	def _build_submission_group(self) -> QtWidgets.QGroupBox:
		group = QtWidgets.QGroupBox('Submission')
		form = QtWidgets.QFormLayout(group)

		self.usd_table = QtWidgets.QTableWidget(0, 2)
		self.usd_table.setHorizontalHeaderLabels(['USD File', 'Overrides'])
		self.usd_table.setSelectionBehavior(QtWidgets.QAbstractItemView.SelectRows)
		self.usd_table.setSelectionMode(QtWidgets.QAbstractItemView.ExtendedSelection)
		self.usd_table.setEditTriggers(QtWidgets.QAbstractItemView.NoEditTriggers)
		self.usd_table.verticalHeader().hide()
		self.usd_table.setTextElideMode(QtCore.Qt.ElideMiddle)
		self.usd_table.setWordWrap(False)
		self.usd_table.setMinimumHeight(140)
		header = self.usd_table.horizontalHeader()
		header.setSectionResizeMode(0, QtWidgets.QHeaderView.Stretch)
		header.setSectionResizeMode(1, QtWidgets.QHeaderView.ResizeToContents)
		self.usd_table.setToolTip(
			'USD files to submit. Each file is submitted as one or more jobs.\n'
			'Select files to override their settings below.')
		self.usd_table.itemSelectionChanged.connect(self._selection_changed)
		form.addRow('USD File/s', self.usd_table)
		form.addRow('', self._build_usd_buttons())
		self.file_panel = FileOverridesPanel(self)
		self.file_panel.changed.connect(self._update_override_summary)
		form.addRow(self.file_panel)

		self.batch_name = QtWidgets.QLineEdit()
		self.batch_name.setToolTip('Name used to group jobs in the Monitor. Ignored if blank.')
		self.batch_name.textEdited.connect(lambda: setattr(self, '_batch_edited', True))
		self.comment = QtWidgets.QLineEdit()
		self.chunk_size = QtWidgets.QSpinBox()
		self.chunk_size.setRange(1, 1000)
		self.chunk_size.setValue(5)
		form.addRow('Batch Name', self.batch_name)
		form.addRow('Comment', self.comment)
		# Inside Houdini the running version selects husk, standalone it is chosen here
		self.version = None
		if not self.running_version:
			self.version = QtWidgets.QComboBox()
			self.version.addItems(HOUDINI_VERSIONS)
			self.version.setToolTip(
				'Houdini version of the husk executable used to render,\n'
				'as set in Configure Plugin > HuskStandalone.')
			form.addRow('Houdini Version', self.version)

		# Inside a rez context, default to its request so the farm renders in the same packages
		self.rez = QtWidgets.QLineEdit(os.environ.get(REZ_REQUEST_VARIABLE) or self.settings.value('rez', ''))
		self.rez.setPlaceholderText('Package request or context file (.rxt)')
		self.rez.setToolTip(
			"Render with husk from a rez context instead of the Houdini Version's husk.\n"
			'A package request, eg. houdini-21.0 ocio_aces, or a context file (.rxt).\n'
			'Ignored if blank. Requires Rez Executable in Configure Plugin > HuskStandalone.')
		self.environment = QtWidgets.QPlainTextEdit(self.settings.value('environment', ''))
		self.environment.setPlaceholderText('KEY=VALUE, one per line')
		self.environment.setFixedHeight(self.environment.fontMetrics().lineSpacing() * 4 + 12)
		self.environment.setToolTip(
			'Environment variables set when rendering, one KEY=VALUE per line.\n'
			"They can also be changed after submission in the job's Environment properties.")
		form.addRow('Rez', self.rez)
		form.addRow('Environment', self.environment)
		form.addRow('Frames Per Task', self.chunk_size)
		form.addRow('Frame Range', self._build_frame_range())
		return group

	def _build_usd_buttons(self) -> QtWidgets.QWidget:
		widget = QtWidgets.QWidget()
		layout = QtWidgets.QHBoxLayout(widget)
		layout.setContentsMargins(0, 0, 0, 0)
		for label, slot in (('Add...', self._browse_usd), ('Remove', self._remove_selected), ('Clear', self._clear_usd)):
			button = QtWidgets.QPushButton(label)
			button.clicked.connect(slot)
			layout.addWidget(button)
		layout.addStretch()
		return widget

	def _build_frame_range(self) -> QtWidgets.QWidget:
		widget = QtWidgets.QWidget()
		layout = QtWidgets.QHBoxLayout(widget)
		layout.setContentsMargins(0, 0, 0, 0)
		self.override_frames = QtWidgets.QCheckBox()
		self.override_frames.setToolTip('Enable to set the frame range explicitly, otherwise use the stage timecodes.')
		self.start_frame, self.end_frame = QtWidgets.QSpinBox(), QtWidgets.QSpinBox()
		for spin_box, value in ((self.start_frame, 1001), (self.end_frame, 1250)):
			spin_box.setRange(-FRAME_LIMIT, FRAME_LIMIT)
			spin_box.setValue(value)
			spin_box.setEnabled(False)
			self.override_frames.toggled.connect(spin_box.setEnabled)
		for item in (self.override_frames, QtWidgets.QLabel('Start'), self.start_frame, QtWidgets.QLabel('End'), self.end_frame):
			layout.addWidget(item)
		return widget

	def _build_option_group(self, group_name: str) -> QtWidgets.QGroupBox:
		group = QtWidgets.QGroupBox(group_name)
		form = QtWidgets.QFormLayout(group)
		for option in OPTIONS:
			if option.group != group_name:
				continue
			row = self.rows[option.flag]
			form.addRow(row.label, row.widget)
			if option.flag == '--settings':
				self.separate_jobs = QtWidgets.QCheckBox('Separate Jobs')
				self.separate_jobs.setToolTip('Submit each render settings prim as a separate job.')
				form.addRow('', self.separate_jobs)
		return group

	def _build_buttons(self) -> QtWidgets.QHBoxLayout:
		layout = QtWidgets.QHBoxLayout()
		layout.addStretch()
		submit = QtWidgets.QPushButton('Submit...')
		submit.setDefault(True)
		submit.clicked.connect(self.submit)
		close = QtWidgets.QPushButton('Close')
		close.clicked.connect(self.close)
		layout.addWidget(submit)
		layout.addWidget(close)
		return layout

	def usd_paths(self) -> list[str]:
		return [self.usd_table.item(row, 0).text() for row in range(self.usd_table.rowCount())]

	def selected_usd_paths(self) -> list[str]:
		rows = sorted({index.row() for index in self.usd_table.selectedIndexes()})
		return [self.usd_table.item(row, 0).text() for row in rows]

	def file_job_options(self) -> dict[Path, JobOptions]:
		'''
		Job options of the USD files with overrides: the shared options with the file's overrides applied.
		Blank Settings, Camera and Output/s overrides are ignored.
		'''
		shared = self.job_options()
		result = {}
		for path, overrides in self.file_overrides.items():
			arguments = dict(shared.arguments)
			changes = {}
			if 'frames' in overrides:
				changes['frame_range'] = overrides['frames']
			if '--renderer' in overrides:
				arguments['--renderer'] = overrides['--renderer']
			if overrides.get('--camera'):
				arguments.update({'override_--camera': 'True', '--camera': overrides['--camera']})
			if '--res' in overrides:
				arguments.update({'override_--res': 'True', '--res': '{} {}'.format(*overrides['--res'])})
			if overrides.get('--settings'):
				changes['settings_pattern'] = overrides['--settings']
			if overrides.get('--output'):
				changes['output_override'] = overrides['--output']
			result[Path(path)] = replace(shared, arguments=arguments, **changes)
		return result

	def shared_value(self, key: str) -> str | tuple[int, int]:
		'''
		Shared setting of a file override, shown for files that don't override it.
		'''
		if key == 'frames':
			return self.start_frame.value(), self.end_frame.value()
		row = self.rows[key]
		if key == '--res':
			return tuple(int(value) for value in row.value().split())
		return row.value() if row.enabled() else ''

	def prim_choices(self, path: str) -> tuple[list[str], list[str]]:
		'''
		RenderSettings and camera prim paths of a USD file, read once.
		'''
		if path not in self._prim_choices:
			QtWidgets.QApplication.setOverrideCursor(QtCore.Qt.WaitCursor)
			try:
				settings = list(read_render_info(Path(path)).settings)
				cameras = read_cameras(Path(path))
			except RenderInfoError:
				settings, cameras = [], []
			finally:
				QtWidgets.QApplication.restoreOverrideCursor()
			self._prim_choices[path] = (settings, cameras)
		return self._prim_choices[path]

	def _selection_changed(self) -> None:
		self.file_panel.set_paths(self.selected_usd_paths())

	def _update_override_summary(self) -> None:
		for row in range(self.usd_table.rowCount()):
			overrides = self.file_overrides.get(self.usd_table.item(row, 0).text(), {})
			summary = ', '.join(label for key, label in FILE_OVERRIDE_LABELS.items() if key in overrides)
			self.usd_table.item(row, 1).setText(summary)

	def add_usd_paths(self, paths: list[str]) -> None:
		existing = set(self.usd_paths())
		for path in paths:
			if path in existing:
				continue
			existing.add(path)
			row = self.usd_table.rowCount()
			self.usd_table.insertRow(row)
			path_item = QtWidgets.QTableWidgetItem(path)
			path_item.setToolTip(path)
			self.usd_table.setItem(row, 0, path_item)
			self.usd_table.setItem(row, 1, QtWidgets.QTableWidgetItem())
		self._update_batch_name()

	def _browse_usd(self) -> None:
		directory = self.settings.value('last_directory', '')
		file_filter = 'All USD Files (*.usd *.usda *.usdc *.usdz);;' + USD_FILE_FILTER
		paths, _ = QtWidgets.QFileDialog.getOpenFileNames(self, 'Select USD files', directory, file_filter)
		if paths:
			self.settings.setValue('last_directory', os.path.dirname(paths[0]))
			self.add_usd_paths(paths)

	def _remove_selected(self) -> None:
		for path in self.selected_usd_paths():
			self.file_overrides.pop(path, None)
		for row in sorted({index.row() for index in self.usd_table.selectedIndexes()}, reverse=True):
			self.usd_table.removeRow(row)
		self._update_batch_name()

	def _clear_usd(self) -> None:
		self.file_overrides.clear()
		self.usd_table.setRowCount(0)
		self._update_batch_name()

	def _update_batch_name(self) -> None:
		if not self._batch_edited:
			self.batch_name.setText(default_batch_name(self.usd_paths()))

	def job_options(self) -> JobOptions:
		def per_job_value(flag: str) -> str:
			row = self.rows[flag]
			return row.value() if row.enabled() else ''

		arguments = {}
		for flag, row in self.rows.items():
			if flag not in PER_JOB_FLAGS:
				arguments.update(row.arguments())
		frame_range = (self.start_frame.value(), self.end_frame.value()) if self.override_frames.isChecked() else None
		return JobOptions(
			arguments=arguments,
			pass_pattern=per_job_value('--pass'),
			settings_pattern=per_job_value('--settings'),
			output_override=per_job_value('--output'),
			separate_jobs=self.separate_jobs.isChecked(),
			frame_range=frame_range)

	def _validate(self) -> str:
		if not self.usd_paths():
			return 'No USD files selected.'
		if self.override_frames.isChecked() and self.end_frame.value() < self.start_frame.value():
			return 'End Frame must be higher than Start Frame.'
		for path, overrides in self.file_overrides.items():
			if 'frames' in overrides and overrides['frames'][1] < overrides['frames'][0]:
				return f'End Frame must be higher than Start Frame for {os.path.basename(path)}.'
		try:
			parse_environment(self.environment.toPlainText())
		except ValueError as error:
			return str(error)
		return ''

	def submit(self) -> None:
		error = self._validate()
		if error:
			QtWidgets.QMessageBox.warning(self, WINDOW_TITLE, error)
			return
		self.settings.setValue('rez', self.rez.text().strip())
		self.settings.setValue('environment', self.environment.toPlainText())

		QtWidgets.QApplication.setOverrideCursor(QtCore.Qt.WaitCursor)
		try:
			jobs, failures = plan_jobs(
				[Path(path) for path in self.usd_paths()], self.job_options(), self.file_job_options())
		finally:
			QtWidgets.QApplication.restoreOverrideCursor()

		preview = JobPreviewDialog(jobs, failures, self)
		if preview.exec() != QtWidgets.QDialog.Accepted:
			return
		results = self._submit_jobs(jobs)
		if results is not None:
			show_results(self, results, failures)

	def _submit_jobs(self, jobs: list[Job]) -> list[SubmitResult] | None:
		try:
			command = find_deadlinecommand()
		except DeadlineError as error:
			QtWidgets.QMessageBox.critical(self, WINDOW_TITLE, str(error))
			return None

		progress = QtWidgets.QProgressDialog('Submitting jobs...', 'Cancel', 0, len(jobs), self)
		progress.setWindowModality(QtCore.Qt.WindowModal)
		results = []
		for index, job in enumerate(jobs):
			if progress.wasCanceled():
				break
			progress.setLabelText(f'Submitting {job.name}')
			progress.setValue(index)
			QtWidgets.QApplication.processEvents()
			results.append(self._submit_one(job, command))
		progress.setValue(len(jobs))
		return results

	def _submit_one(self, job: Job, command: Path) -> SubmitResult:
		try:
			return submit_job(
				job, command, batch_name=self.batch_name.text().strip(), comment=self.comment.text(),
				chunk_size=self.chunk_size.value(),
				houdini_version=self.running_version or self.version.currentText(),
				environment=parse_environment(self.environment.toPlainText()), rez=self.rez.text())
		except DeadlineError as error:
			return SubmitResult(job, False, '', str(error))


class JobPreviewDialog(QtWidgets.QDialog):
	'''
	Lists the jobs about to be submitted. Outputs can be edited per job and
	output paths shared by several jobs are flagged. Edits are applied to the jobs.
	'''

	def __init__(self, jobs: list[Job], failures: dict[str, str], parent: QtWidgets.QWidget | None = None) -> None:
		super().__init__(parent)
		self.setWindowTitle(f'{WINDOW_TITLE} - Review Jobs')
		self.resize(900, 400)
		self.jobs = jobs
		layout = QtWidgets.QVBoxLayout(self)

		for path, error in failures.items():
			layout.addWidget(self._label(f'Skipped {path}:\n    {error}'))
		self.collision_label = self._label(
			'Highlighted outputs are written by more than one job. Edit them below '
			'or use {usd}, {pass} or {settings} in Output/s to make them unique.')
		layout.addWidget(self.collision_label)
		self.table = self._build_table(jobs)
		self.table.itemChanged.connect(self._output_edited)
		layout.addWidget(self.table)

		buttons = QtWidgets.QDialogButtonBox(QtWidgets.QDialogButtonBox.Cancel)
		submit = buttons.addButton(f'Submit {len(jobs)} Job/s', QtWidgets.QDialogButtonBox.AcceptRole)
		submit.setEnabled(bool(jobs))
		buttons.accepted.connect(self.accept)
		buttons.rejected.connect(self.reject)
		layout.addWidget(buttons)
		self._refresh_outputs()

	@staticmethod
	def _label(text: str) -> QtWidgets.QLabel:
		label = QtWidgets.QLabel(text)
		label.setWordWrap(True)
		label.setTextInteractionFlags(QtCore.Qt.TextSelectableByMouse)
		return label

	@staticmethod
	def _build_table(jobs: list[Job]) -> QtWidgets.QTableWidget:
		table = QtWidgets.QTableWidget(len(jobs), 3)
		table.setHorizontalHeaderLabels(['Job', 'Frames', 'Outputs'])
		table.setEditTriggers(QtWidgets.QAbstractItemView.DoubleClicked | QtWidgets.QAbstractItemView.EditKeyPressed)
		table.horizontalHeader().setStretchLastSection(True)
		for row, job in enumerate(jobs):
			for column, text in enumerate((job.name, job.frames)):
				item = QtWidgets.QTableWidgetItem(text)
				item.setFlags(item.flags() & ~QtCore.Qt.ItemIsEditable)
				table.setItem(row, column, item)
			table.setItem(row, OUTPUTS_COLUMN, QtWidgets.QTableWidgetItem())
		return table

	def _output_edited(self, item: QtWidgets.QTableWidgetItem) -> None:
		if item.column() == OUTPUTS_COLUMN:
			set_outputs(self.jobs[item.row()], item.text())
			self._refresh_outputs()

	def _refresh_outputs(self) -> None:
		'''
		Show each job's outputs with tokens expanded and highlight shared ones.
		'''
		collisions = set(find_output_collisions(self.jobs))
		self.table.blockSignals(True)
		for row, job in enumerate(self.jobs):
			item = self.table.item(row, OUTPUTS_COLUMN)
			shared = sorted(collisions.intersection(job.outputs))
			item.setText(', '.join(job.outputs))
			item.setForeground(COLLISION_COLOR if shared else self.table.palette().text().color())
			item.setToolTip('\n'.join([OUTPUTS_TOOLTIP, *shared]))
		self.table.blockSignals(False)
		self.collision_label.setVisible(bool(collisions))
		self.table.resizeColumnsToContents()


def show_results(parent: QtWidgets.QWidget, results: list[SubmitResult], failures: dict[str, str]) -> None:
	succeeded = [result for result in results if result.success]
	failed = [result for result in results if not result.success]
	summary = f'{len(succeeded)} job/s submitted, {len(failed)} failed, {len(failures)} file/s skipped.'

	details = [f'OK      {result.job.name} ({result.job_id})' for result in succeeded]
	details += [f'FAILED  {result.job.name}\n{result.output.strip()}' for result in failed]
	details += [f'SKIPPED {path}\n{error}' for path, error in failures.items()]

	box = QtWidgets.QMessageBox(parent)
	box.setWindowTitle(f'{WINDOW_TITLE} - Results')
	box.setIcon(QtWidgets.QMessageBox.Warning if failed or failures else QtWidgets.QMessageBox.Information)
	box.setText(summary)
	box.setDetailedText('\n\n'.join(details))
	box.exec()


def show(usd_paths: list[str] | None = None) -> SubmitterDialog:
	'''
	Open the submitter parented to the Houdini main window.
	'''
	global _dialog
	parent = None
	try:
		import hou
		parent = hou.qt.mainWindow()
	except ImportError:
		pass
	_dialog = SubmitterDialog(parent, usd_paths)
	_dialog.show()
	return _dialog


def main() -> None:
	logging.basicConfig(level=logging.INFO)
	app = QtWidgets.QApplication.instance() or QtWidgets.QApplication(sys.argv)
	dialog = SubmitterDialog(usd_paths=[path for path in sys.argv[1:] if os.path.isfile(path)])
	dialog.show()
	app.exec()


if __name__ == '__main__':
	main()
