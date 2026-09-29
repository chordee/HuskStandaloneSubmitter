import os
import pathlib
import subprocess
import re
from collections import Counter
from enum import Enum
from functools import partial
from dataclasses import dataclass, field
from typing import Callable, Optional, Literal

from Deadline.Scripting import ClientUtils, RepositoryUtils, FileUtils, FrameUtils
from DeadlineUI.Controls.Scripting.DeadlineScriptDialog import DeadlineScriptDialog
from ThinkboxUI.Controls.CollapsibleGroupBox import CollapsibleGroupBox
from System import Array
from System.Text import Encoding
from System.IO import Path, StreamWriter
from System.Collections.Specialized import StringCollection


class ControlType(Enum):
	label = 'LabelControl'
	text = 'TextControl'
	multifile = 'MultiFileBrowserControl'
	filesaver = 'FileSaverControl'
	checkbox = 'CheckBoxControl'
	range = 'RangeControl'
	range2 = 'RangeControl2'
	button = 'ButtonControl'
	combo = 'ComboControl'
	multilist = 'MultiSelectListControl'


@dataclass
class Control:
	name: str
	label: str
	type: ControlType
	value: list 
	tooltip: str = ''
	override: bool | None = None
	pre_space: bool = False
	callback: Optional[Callable[[DeadlineScriptDialog], None]] = None


@dataclass
class RenderInfo:
	startTimeCode: int = 1
	endTimeCode: int = 1
	renderSettingsPrimPath: str = '/Render/rendersettings'
	ProductName: list[str] = field(default_factory=list)
	RenderVar: list[str] = field(default_factory=list)
	RenderProduct: list[str] = field(default_factory=list)
	RenderSettings: list[str] = field(default_factory=list)
	RenderPass: list[str] = field(default_factory=list)
	relationships: dict[str, list[str]] = field(default_factory=dict)


@dataclass
class JobSubmission:
	name: str
	frame_list: str
	productnames: list[str]
	arguments: dict = field(default_factory=dict)


def get_usdcat(version: str) -> str:
	'''
	Returns the usdcat executable next to the husk executable of the Houdini version.
	'''
	husk_settings = RepositoryUtils.GetPluginConfig('HuskStandalone')
	config_key = f'Houdini{version.replace(".", "_")}_Husk_Executable'
	executable_list = husk_settings.GetConfigEntryWithDefault(config_key, '')
	executable = FileUtils.SearchFileList(executable_list)
	if not executable:
		raise Exception(f"Husk executable for Houdini {version} not found.\nSet {config_key} in Configure Plugin.")

	husk = pathlib.Path(executable)
	usdcat = husk.with_name('usdcat' + husk.suffix)

	if not usdcat.exists():
		raise Exception("Houdini usdcat binary not found.")

	return str(usdcat)


def save_browser_location(path: str) -> None:
	txt_path = Path.Combine( GetDeadlineTempPath(), 'husk_browser_location.txt' )
	with open(txt_path, 'w') as file:
		file.write(path)


def load_browser_location() -> str:
	txt_path = Path.Combine( GetDeadlineTempPath(), 'husk_browser_location.txt' )
	if not os.path.exists(txt_path):
		return ''
	with open(txt_path, 'r') as file:
		return file.read()


def files_selected(dialog: DeadlineScriptDialog):
	'''
	Sets the Batch Name to the shortest common prefix of input files
	when multiple files are selected.

	eg. Scene_v005.FG.usd;Scene_v005.BG.usd -> Scene_v005
	'''
	file_paths_string = dialog.GetValue('file_paths_control')
	if not file_paths_string:
		return

	file_paths = file_paths_string.split(';')
	save_browser_location(os.path.dirname(file_paths[0]))

	# Uncomment to stop auto batching on single files
	# Means that multiple passes won't be batched by default
	# if len(file_paths) == 1:
	# 	dialog.SetValue('batch_control', '')
	# 	return
	
	common_prefix = os.path.commonprefix(file_paths)
	batch_name = os.path.basename(os.path.splitext(common_prefix)[0])
	if common_prefix:
		dialog.SetValue('batch_control', batch_name)


# Define UI
HOUDINI_VERSIONS = ['21.0', '22.0']
WINDOW_TITLE = 'Deadline Husk Submitter'
MAX_COLUMNS = 6
MAX_LISTED_COLLISIONS = 5
OUTPUT_TOKEN_PATTERN = re.compile(r'\{(usd|pass|settings)\}')
CONTROLS = {  # End key with _,+ or - for group, expanded group or collapsed group
	'Submission_': [
		[Control(
			name = 'file_paths_control',
			label = 'USD File/s',
			type = ControlType.multifile,
			value = ['', 'USD Files (*.usd);;USDA Files (*.usda);;USDC Files(*.usdc);;USDZ Files(*.usdz)'],
			tooltip = "Select USD files to submit to Husk.\nSemicolon (;) separated list.",
			callback=files_selected)],
		[Control(
			name = 'batch_control',
			label = 'Batch Name',
			type = ControlType.text,
			value = [''],
			tooltip = (
				"Name used to group render jobs together in the Monitor.\n"
				"Ignored if blank.\n"
				"Defaults to the shortest filename prefix of input files."))],
		[Control(
			name = 'comment_control',
			label = 'Comment',
			type = ControlType.text,
			value = [''],
			tooltip = "A comment for the job to display in the Monitor")],
		[Control(
			name = 'version_control',
			label = 'Houdini Version',
			type = ControlType.combo,
			value = [HOUDINI_VERSIONS[0], HOUDINI_VERSIONS],
			tooltip = (
				"Houdini version of the husk executable used to render,\n"
				"as set in Configure Plugin > HuskStandalone."))],
		[Control(
			name = 'chunk_control',
			label = 'Frames Per Task',
			type = ControlType.range,
			value = [5, 1, 1000, 0, 1],
			tooltip = "Specify how many frames to render per task.")],
		[Control(
			name = 'framerange_control',
			label = 'Frame Range',
			type = ControlType.range2,
			value = [('Start', [1001, -65535, 65535, 0, 1]), ('End', [1250, -65535, 65535, 0, 1])],
			override=False,
			tooltip = (
				"Enable to explicitly set the frame range to render.\n"
				"Otherwise use the authored startTimeCode and endTimecode."))],
	],

	'Rendering-': [
		[Control(
			name = '--renderer',
			label = 'Renderer',
			type = ControlType.combo,
			value = ['', ['BRAY_HdKarmaXPU', 'BRAY_HdKarma', 'HdRedshiftRendererPlugin']],
			tooltip = "Specify Hydra client.")],
		[Control(
			name = '--pixel-samples',
			label = 'Pixel Samples',
			type = ControlType.range,
			value = [128, 1, 65535, 0, 1],
			override=False,
			tooltip = "Enable to override samples per pixel.")],
		[Control(
			name = '--pass',
			label = 'Pass Prim/s',
			type = ControlType.text,
			value = [''],
			override=False,
			tooltip = (
				"Render using the RenderPass prim/s specified.\n"
				"Multiple render passes can be specified "
				"using a comma or space separated list and/or pattern matching.\n"
				"Custom submission implementation to match --settings UX.\n"
				"Each pass is submitted as a separate render job."))],
		[Control(
			name = '--settings',
			label = 'Settings Prim/s',
			type = ControlType.text,
			value = [''],
			override=False,
			tooltip = (
				"Render using the RenderSettings prim/s specified.\n"
				"Multiple render settings can be specified "
				"using a comma or space separated list and/or pattern matching.\n"
				"When disabled or blank defaults to either the RenderPass.renderSource "
				"(if --pass is set) or the layer's renderSettingsPrimPath metadata."))],
		[Control(
			name = 'separate_jobs',
			label = '',
			type = ControlType.checkbox,
			value = [False, 'Separate Jobs'],
			tooltip = (
				'Submit each specified render settings prim as a separate render job.'))],
		[Control(
			name = '--slap-comp',
			label = 'Slap Comp',
			type = ControlType.text,
			value = [''],
			override=False,
			tooltip = (
				"Path to Apex COP .geo file to run on outputs.\n"
				"Options encoded using: path_to_graph?option=value&option2=value2."))],
		[Control(
			name = '--tile-count',
			label = 'Auto Tile',
			type = ControlType.range2,
			value = [('x', [4, 1, 65535, 0, 1]), ('y', [4, 1, 65535, 0, 1])],
			override=False,
			tooltip = (
			"Enable autotiling, where Husk will render x by y tiles\n"
			"and stitch them together on completion."))],
		[Control(
			name = '--verbose',
			label = 'Logging Verbosity',
			type = ControlType.range,
			value = [0, 0, 9, 0, 1],
			tooltip = (
				"Verbosity of rendering statistics.\n"
				"Note that verbose levels of 8 and greater may affect "
				"rendering performance and should only be used for debugging problem scenes."))],
	],

	'RenderSettingsOverrides-': [
		[Control(
			name = '--res',
			label = 'Resolution',
			type = ControlType.range2,
			value = [('x', [1920, 0, 65535, 0, 1]), ('y', [1080, 0, 65535, 0, 1])],
			override=False,
			tooltip = "Rendered image width and height, in pixels.")],
		[Control(
			name = '--res-scale',
			label = 'Resolution Scale',
			type = ControlType.range,
			value = [100, 0, 5000, 0, 1],
			override=False,
			tooltip = "Scale the output image by the given percentage.")],
		[Control(
			name = '--camera',
			label = 'Camera',
			type = ControlType.text,
			value = [''],
			override=False,
			tooltip = "The primitive path of the camera to render from.")],
		[Control(
			name = '--output',
			label = 'Output/s',
			type = ControlType.filesaver,
			value = ['', ''],
			override=False,
			tooltip = (
				"Comma separated list of output image file paths.\n"
				"These can contain certain local variables:\n"
				"eg. $F/<F>/%d, $F4/<F4>/%04d, $FF/<FF>/%g\n"
				"Submitter tokens expanded per job:\n"
				"{usd} USD file name, {pass} RenderPass name, {settings} RenderSettings name"))],
	],

	'USD-': [
		[Control(
			name = '--headlight',
			label = 'Headlight',
			type = ControlType.combo,
			value = ['', ['None', 'Distant', 'Dome']],
			override=True,
			tooltip = (
				"When there are no lights found on the stage,\n"
				"this controls the headlight mode."))],
		[Control(
			name = '--disable-scene-materials',
			label = '',
			type = ControlType.checkbox,
			value = [False, 'Disable Scene Materials'],
			tooltip = (
				"Disable all materials in the scene.\n"
				"This option applies to all render delegates."))],
		[Control(
			name = '--disable-scene-lights',
			label = '',
			type = ControlType.checkbox,
			value = [False, 'Disable Scene Lights'],
			tooltip = (
				"Disable all lights in the scene.\n"
				"This option applies to all render delegates."))],
		[Control(
			name = '--disable-motionblur',
			label = '',
			type = ControlType.checkbox,
			value = [False, 'Disable Motion Blur'],
			tooltip = (
				"Disable motion blur in the scene.\n"
				"This option applies to all render delegates."))],
	],
}


def generate_options_file() -> None:
	'''
	Generate the HuskStandalone.options file in the repo plugin directory.
	The options are generated based on the parameters specified
	in the CONTROLS variable. 
	'''
	plugin_directory = RepositoryUtils.GetPluginDirectory('HuskStandalone')
	options_path = Path.Combine( plugin_directory, 'HuskStandalone.options' )
	writer = StreamWriter( options_path, False, Encoding.UTF8 )

	index = 0
	for category_index, (group, controls) in enumerate(CONTROLS.items()):
		category = group.rstrip('_+-')
		for control_row in controls:
			for control in control_row:
				names = []

				if control.name == 'file_paths_control':
					names = ['--usd-input']
				elif not control.name.startswith('--'):
					continue
				else:
					if control.override is not None:
						names.append(f'override_{control.name}')
					names.append(control.name)

				for name in names:
					writer.WriteLine( f'[{name}]' )

					writer.WriteLine( f'Category={category}' )
					writer.WriteLine( f'CategoryOrder={category_index}' )
					writer.WriteLine( f'Index={index}' )

					if name.startswith('override_'):
						writer.WriteLine( f'Description=Enables {name.lstrip("override_")} Husk option.' )
						writer.WriteLine( f'Label=Enable {control.label}' )
						writer.WriteLine( 'Type=Boolean' )
						writer.WriteLine( f'DefaultValue={control.override}' )
						writer.WriteLine( '' )
						index += 1
						continue

					writer.WriteLine( f'Description={control.tooltip}' )

					label = control.label
					default = control.value[0]
					option_type = 'String'

					if name == '--usd-input':
						option_type = 'Filename'
						writer.WriteLine( f'Filter={control.value[1]}' )
					elif name == '--output':
						option_type = 'FilenameSave'
						writer.WriteLine( f'Filter={control.value[1]}' )

					match control.type:
						case ControlType.checkbox:
							option_type = 'Boolean'
							label = control.value[1]
						case ControlType.range:
							decimal_places = control.value[3]
							if decimal_places == 0:
								option_type = 'Integer'
							else:
								option_type = 'Float'
								writer.WriteLine( f'DecimalPlaces={decimal_places}' )
							writer.WriteLine( f'Minimum={control.value[1]}' )
							writer.WriteLine( f'Maximum={control.value[2]}' )
							writer.WriteLine( f'Increment={control.value[4]}' )
						case ControlType.range2:
							default = f'{control.value[0][1][0]} {control.value[1][1][0]}'
						case ControlType.combo:
							option_type = 'Enum'
							default = control.value[1][0]
							writer.WriteLine( f'Values={";".join(control.value[1])}' )

					writer.WriteLine( f'DefaultValue={default}' )
					writer.WriteLine( f'Type={option_type}' )
					writer.WriteLine( f'Label={label}' )
					writer.WriteLine( '' )
					index += 1

	writer.Close()


def get_render_info(path: str, usdcat_executable: str) -> RenderInfo:
	'''
	Returns a RenderInfo dataclass representing relevant layer metadata
	and all of the render prims and their relationships.
	Hacky parsing of usdcat output to avoid dealing with clashing
	Deadline/USD python versions.
	Only looks under /Render.
	ProductName will always be the last element of the RenderProduct's
	relationship list and will be the first found frame converted to printf format.
	'''
	result = RenderInfo()
	accum_path:str = ''
	accum_depth:int = -1

	# CREATE_NO_WINDOW only exists on Windows
	creationflags = getattr(subprocess, 'CREATE_NO_WINDOW', 0)
	usdcat = subprocess.check_output([usdcat_executable, '--flatten', '--mask', '/Render', path], text=True, creationflags=creationflags)
	finished_metadata = False
	resume = []
	for line in usdcat.splitlines():
		# Process metadate first
		if not finished_metadata:
			if line.strip() == ')':
				finished_metadata = True
				continue
			elif ' = ' not in line:
				continue
			
			key, value = line.lstrip().split(' = ')
			if hasattr(result, key):
				setattr(result, key, value.strip('"'))

			continue
		# Resume list
		if resume:
			if resume[1] in line:
				resume = []
				continue

			if resume[0] == 'skip':
				continue
			
			match = re.search(resume[0], line)
			if not match:
				resume = []
				continue

			matched_path = match.group(1)

			if resume[1] == '}':
				matched_path = FrameUtils.ReplaceFrameNumberWithPrintFPadding(matched_path)
				result.ProductName.append(matched_path)

			result.relationships[accum_path].append(matched_path)

			if resume[1] == '}':
				resume[0] = 'skip'
			continue

		# Find Render Prims
		match = re.search(r'def (?P<type>.+) "(?P<name>.+)"', line)
		if match:
			name = match.groupdict()['name']
			prim_type = match.groupdict()['type']

			current_depth:int = (len(line) - len(line.lstrip())) // 4
			if current_depth > accum_depth:
				accum_depth = current_depth
				accum_path += f'/{name}'
			elif current_depth <= accum_depth:
				diff = accum_depth - current_depth
				for _ in range(diff + 1):
					accum_path, _ = os.path.split(accum_path) 
				accum_depth -= diff
				accum_path += f'/{name}'

			if hasattr(result, prim_type):
				getattr(result, prim_type).append(accum_path)
			continue

		# Find Relationships
		match = re.search(r'(?:rel|token) (?P<type>products|renderSource|orderedVars|productName(?:\.timeSamples)?) = (?P<path>.+)', line)
		if match:
			matched_path = match.groupdict()['path'].strip('<>"')
			prim_type = match.groupdict()['type']

			if prim_type == 'productName':
				result.ProductName.append(matched_path)

			if accum_path not in result.relationships:
				result.relationships[accum_path] = []

			if matched_path == '[':
				resume = [r'<(.*)>', ']']
			elif matched_path == '{': 
				resume = [r'\d+: "(.+)",', '}']
			else:
				result.relationships[accum_path].append(matched_path)

	return result


def toggle_enabled(dialog: DeadlineScriptDialog) -> None:
	for control_rows in CONTROLS.values():
		for control_row in control_rows:
			for control in control_row:
				if control.override is None:
					continue
				enabled = dialog.GetValue(f'override_{control.name}')
				if control.label:
					dialog.SetEnabled(f'{control.name}_label', enabled)

				if control.type is not ControlType.range2:
					dialog.SetEnabled(control.name, enabled)
				else:
					for i, (label, _) in enumerate(control.value):
						if label:
							dialog.SetEnabled(f'{control.name}_{i}_label', enabled)
						dialog.SetEnabled(f'{control.name}_{i}', enabled)


def format_results_message(results: dict[str, dict[str, str]]) -> str:
	'''
	Take the stdout results of the job submissions and format them nicely for display.
	'''
	result_output = ''
	for k, v in results.items():
		if not v:
			continue

		if k == 'success':
			result_output += '---| Successful Submissions |---\n'
		else:
			result_output += '-!!|   Failed Submissions   |!!-\n'

		for job_name, stdout in v.items():
			result_output += f'{job_name}\n'
			if k == 'fail':
				result_output += ''.join([f'\t{s}' for s in stdout.splitlines(True) if s.strip()])
				result_output += '\n'

		result_output += '\n'

	result_output = result_output.rstrip()
	return result_output


def parse_prim_pattern(
	patterns: str, render_info: RenderInfo,
	prim_type: Literal['RenderPass', 'RenderSettings']) -> list[str]:
	'''
	Takes string representing a comma or space separated list of primpaths
	with patterns and returns a list of matching primpaths.

	Examples:
	RenderPass: '*' -> matches all RenderPass Prims in render_info
	RenderSettings: '*' -> matches all RenderSettings Prims in render_info
	RenderSettings: 'preview1,final*' -> matches RenderSettings named 'preview1'
					along with any beginning with 'final'
	'''
	result = []
	valid_paths = getattr(render_info, prim_type)

	for pattern in re.split(r'[,\s]+', patterns):
		regex_string = pattern.replace('*', '.*')
		if not regex_string.startswith('/'):
			regex_string = '/' + regex_string
		regex = re.compile(regex_string)
		result.extend(list(filter(regex.search, valid_paths)))

	return result


def determine_outputs(render_info: RenderInfo, pass_value: str, settings_value: str, output_value: str) -> dict[str, dict[str, list[str]]]:
	'''
	Determines the appropriate values for settings and output for each pass
	based on the values provided by looking into the usd file.
	Pass > Settings > Product > ProductName
	Render Pass drives Render Settings (via RenderSource attribute)
	Render Settings drives Render Product
	Render Product drives output/ProductNames

	Outputs a dictionary with passes as keys
	and the values as dictionaries with settings as keys and lists of productnames as values.
	eg. {'pass1': {settings1: [productname1, productname2]}}}
	'''
	result = {}
	pass_prims = parse_prim_pattern(pass_value, render_info, 'RenderPass') if pass_value else []
	settings_prims = parse_prim_pattern(settings_value, render_info, 'RenderSettings') if settings_value else []
	productnames = [x.strip() for x in output_value.split(',')] if output_value else []

	if not pass_prims:
		pass_prims.append('')

	for pass_prim in pass_prims:
		# First determine render settings
		if pass_prim == '':
			pass_settings = [render_info.renderSettingsPrimPath]
		else:
			pass_settings = render_info.relationships[pass_prim]

		# Use override render settings if supplied
		if settings_prims:
			pass_settings = settings_prims

		# Next determine associated productnames
		# Use override productnames if supplied
		if productnames:
			result[pass_prim] = {pass_setting: productnames for pass_setting in pass_settings}
			continue

		# Get product names from products from settings
		pass_settings_dict = {}
		for pass_setting in pass_settings:
			pass_settings_dict[pass_setting] = []
			for pass_setting_product in render_info.relationships[pass_setting]:
				for pass_setting_productname in render_info.relationships[pass_setting_product]:
					if pass_setting_productname in render_info.ProductName:
						pass_settings_dict[pass_setting].append(pass_setting_productname)

		result[pass_prim] = (pass_settings_dict)

	return result


def get_argument_values(dialog: DeadlineScriptDialog) -> dict:
	'''
	Collect the husk argument values and their override toggles from the dialog.
	'''
	arguments = {}
	for control_rows in CONTROLS.values():
		for control_row in control_rows:
			for control in control_row:
				if not control.name.startswith('--'):
					continue

				if control.override is not None:
					override_name = f'override_{control.name}'
					arguments[override_name] = dialog.GetValue(override_name)

				if control.type is ControlType.range2:
					value0 = dialog.GetValue(f'{control.name}_0')
					value1 = dialog.GetValue(f'{control.name}_1')
					arguments[control.name] = f'{value0} {value1}'
				else:
					arguments[control.name] = dialog.GetValue(control.name)

	return arguments


def group_prim_submissions(
	outputs: dict[str, dict[str, list[str]]],
	separate_jobs: bool) -> list[tuple[str, list[str], list[str]]]:
	'''
	Group the determined outputs into (pass, settings prims, productnames) per job.
	One job per pass, or one job per pass and settings prim when separate_jobs is set.
	'''
	prim_submissions = []
	for pass_prim, pass_settings_dict in outputs.items():
		if not separate_jobs:
			settings_prims = list(pass_settings_dict.keys())
			# Dedupe while preserving order, as --output maps to products by position
			productnames = list(dict.fromkeys(pn for pn_list in pass_settings_dict.values() for pn in pn_list))
			prim_submissions.append((pass_prim, settings_prims, productnames))
		else:
			for settings_prim, productnames in pass_settings_dict.items():
				prim_submissions.append((pass_prim, [settings_prim], productnames))

	return prim_submissions


def expand_output_tokens(path: str, usd_file_path: str, pass_prim: str, settings_prims: list[str]) -> str:
	'''
	Expand submitter tokens in an output path.
	Husk variables such as $F4 and <F4> are left for husk to expand.

	{usd}: USD file name without extension
	{pass}: RenderPass prim name, empty when no pass is used
	{settings}: RenderSettings prim name, the first one when a job renders multiple
	'''
	tokens = {
		'usd': os.path.splitext(os.path.basename(usd_file_path))[0],
		'pass': os.path.basename(pass_prim),
		'settings': os.path.basename(settings_prims[0]) if settings_prims else '',
	}
	expanded = OUTPUT_TOKEN_PATTERN.sub(lambda match: tokens[match.group(1)], path)
	# Collapse separators doubled by empty tokens, keeping a leading UNC prefix
	return re.sub(r'(?<=.)[\\/]{2,}', '/', expanded)


def build_jobs(dialog: DeadlineScriptDialog, usd_file_path: str, arguments: dict, usdcat_executable: str) -> list[JobSubmission]:
	'''
	Parse the USD file and build the jobs to submit for it.
	'''
	render_info: RenderInfo = get_render_info(usd_file_path, usdcat_executable)
	separate_jobs = dialog.GetValue('separate_jobs')

	if dialog.GetValue('override_framerange_control'):
		frame_list = f"{dialog.GetValue('framerange_control_0')}-{dialog.GetValue('framerange_control_1')}"
	else:
		# Use frame range from usd file
		frame_list = f"{render_info.startTimeCode}-{render_info.endTimeCode}"

	outputs = determine_outputs(
			render_info,
			*(arguments[x] if arguments[f'override_{x}'] else ''
			for x in ('--pass', '--settings', '--output'))
		)

	jobs = []
	for pass_prim, settings_prims, productnames in group_prim_submissions(outputs, separate_jobs):
		job_arguments = arguments.copy()
		if pass_prim == '':
			job_arguments['override_--pass'] = False
		job_arguments['--pass'] = pass_prim
		job_arguments['override_--settings'] = True
		job_arguments['--settings'] = ','.join(settings_prims)
		productnames = [
			expand_output_tokens(pn, usd_file_path, pass_prim, settings_prims)
			for pn in productnames]
		job_arguments['override_--output'] = True
		job_arguments['--output'] = ','.join(productnames)
		job_arguments['--usd-input'] = usd_file_path

		job_name_suffix = ''
		if pass_prim != '':
			job_name_suffix = '_' + os.path.basename(pass_prim)
		if separate_jobs:
			job_name_suffix += '_' + os.path.basename(settings_prims[0])

		jobs.append(JobSubmission(
			name = os.path.basename(usd_file_path) + job_name_suffix,
			frame_list = frame_list,
			productnames = productnames,
			arguments = job_arguments))

	return jobs


def submit_job(job: JobSubmission, batch_name: str, comment: str, chunk_size: int, version: str) -> str:
	'''
	Write the job and plugin info files and submit them to Deadline.
	Returns the deadlinecommand output.
	'''
	#Create Job file
	job_info_filename = Path.Combine( GetDeadlineTempPath(), 'husk_job_info.job' )
	writer = StreamWriter( job_info_filename, False, Encoding.Unicode )
	writer.WriteLine( 'Plugin=HuskStandalone' )
	writer.WriteLine( f'Name={job.name}')
	if batch_name:
		writer.WriteLine( f'BatchName={batch_name}')
	writer.WriteLine( f'Comment={comment}')
	writer.WriteLine( f'Frames={job.frame_list}')
	writer.WriteLine( f'ChunkSize={chunk_size}')
	for i, productname in enumerate(job.productnames):
		writer.WriteLine( f'OutputFilename{i}={productname}' )
	writer.Close()

	# Create plugin info file.
	plugin_info_filename = Path.Combine( GetDeadlineTempPath(), 'husk_plugin_info.job' )
	writer = StreamWriter( plugin_info_filename, False, Encoding.Unicode )
	writer.WriteLine( f'ArgumentList={";".join(job.arguments.keys())}')
	for argument, value in job.arguments.items():
		writer.WriteLine( f'{argument}={value}' )
	writer.WriteLine( f'Version={version}' )
	writer.Close()

	# Setup the command line arguments.
	job_arguments = StringCollection()
	job_arguments.Add( job_info_filename )
	job_arguments.Add( plugin_info_filename )

	return ClientUtils.ExecuteCommandAndGetOutput( job_arguments )


def submit_pressed(dialog: DeadlineScriptDialog) -> None:
	usd_file_paths_string = dialog.GetValue('file_paths_control')
	
	if not usd_file_paths_string:
		dialog.ShowMessageBox('No USD Files Selected', 'Error')
		return

	usd_file_paths = usd_file_paths_string.split(';')

	# Ensure valid framerange
	if (dialog.GetValue('override_framerange_control')
			and not dialog.GetValue('framerange_control_1') >= dialog.GetValue('framerange_control_0')):
		dialog.ShowMessageBox( "End Frame must be higher than Start Frame", "Error" )
		return

	version = dialog.GetValue('version_control')
	try:
		usdcat_executable = get_usdcat(version)
	except Exception as error:
		dialog.ShowMessageBox(str(error), 'Error')
		return

	arguments = get_argument_values(dialog)

	# Build every job up front so nothing is submitted if the user cancels
	results = {'success': {}, 'fail': {}}
	jobs: list[JobSubmission] = []
	for usd_file_path in usd_file_paths:
		if not os.path.exists(usd_file_path):
			dialog.ShowMessageBox( "USD file doesn't exist!\n" + usd_file_path, 'Error' )
			results['fail'][usd_file_path] = "USD file doesn't exist"
			continue
		# A usdcat failure on one file should not abort the whole submission
		try:
			jobs.extend(build_jobs(dialog, usd_file_path, arguments, usdcat_executable))
		except (subprocess.CalledProcessError, OSError) as error:
			results['fail'][usd_file_path] = f'Failed to read USD file: {error}'

	# Warn when multiple jobs would write to the same output files
	output_counts = Counter(pn for job in jobs for pn in set(job.productnames))
	collisions = [pn for pn, count in output_counts.items() if count > 1]
	if collisions:
		answer = dialog.ShowMessageBox(
			'Multiple render jobs will write to the same output files:\n'
			+ '\n'.join(collisions[:MAX_LISTED_COLLISIONS])
			+ ('\n...' if len(collisions) > MAX_LISTED_COLLISIONS else '')
			+ '\n\nUse {usd}, {pass} or {settings} in Output/s to make them unique.\n'
			'Continue submitting?',
			'Warning', ('Yes', 'No'))
		if answer != 'Yes':
			return

	batch_name = dialog.GetValue('batch_control')
	comment = dialog.GetValue('comment_control')
	chunk_size = dialog.GetValue('chunk_control')

	for job_index, job in enumerate(jobs):
		# Progress in titlebar
		dialog.SetTitle(f'{WINDOW_TITLE} - Submitting Job {job_index + 1}/{len(jobs)}')
		result = submit_job(job, batch_name, comment, chunk_size, version)
		# Key by directory and job name so same-named USD files in different directories stay separate
		result_key = os.path.join(os.path.dirname(job.arguments['--usd-input']), job.name)
		results['success' if 'Result=Success' in result else 'fail'][result_key] = result

	# Display results/errors
	dialog.SetTitle(f'{WINDOW_TITLE} - Submission Complete')
	dialog.ShowMessageBox( format_results_message(results), "Submission Results" )
	dialog.SetTitle(WINDOW_TITLE)


def submission_dialog(*args) -> DeadlineScriptDialog:
	dialog = DeadlineScriptDialog()
	dialog.SetTitle(WINDOW_TITLE)
	dialog.SetIcon(dialog.GetIcon('HuskStandalone'))

	for group, control_rows in CONTROLS.items():
		in_group = False
		is_collapsed = False
		if group[-1] in '_+-':
			collapsible = group[-1]!='_'
			group_box = dialog.AddGroupBox('', group.rstrip('_+-'), collapsible=collapsible)
			if collapsible:
				group_box.clicked.connect(lambda: dialog.setFixedHeight(dialog.sizeHint().height()))
			in_group = True
			is_collapsed = group[-1] == '-'

		row, column = 0, 0
		dialog.AddGrid()

		for control_row in control_rows:
			for control in control_row:
				if control.pre_space:
					dialog.AddHorizontalSpacerToGrid('', row, column)
					column += 1

				# No need for overrides on checkboxes with no label
				if not (control.type is ControlType.checkbox and not control.label):
					override = dialog.AddSelectionControlToGrid(f'override_{control.name}', ControlType.checkbox.value, control.override, '', row, column, control.tooltip, expand=False)
					override.ValueModified.connect(partial(toggle_enabled, dialog))
					column += 1
					if control.override is None:
						override.setVisible(False)

				if control.label:
					dialog.AddControlToGrid(f'{control.name}_label',
						ControlType.label.value, control.label, row, column, colSpan=1, expand=False)
					column += 1

				control_args = [control.name, control.type.value, *control.value, row, column, control.tooltip]
				control_kwargs = {
					'expand': control.type not in [ControlType.button, ControlType.checkbox],
					'colSpan': MAX_COLUMNS - column,
				}

				if control.type in [ControlType.multifile, ControlType.filesaver]:
					control_kwargs['browserLocation'] = load_browser_location()
				
				control_items = []
				match control.type:
					case ControlType.multifile | ControlType.filesaver | ControlType.checkbox:
						control_items.append(dialog.AddSelectionControlToGrid(*control_args, **control_kwargs))
					case ControlType.range:
						control_items.append(dialog.AddRangeControlToGrid(*control_args, **control_kwargs))
					case ControlType.range2:
						for item_num, item in enumerate(control.value):
							label, value = item
							control_kwargs['colSpan'] = 2
							control_kwargs['expand'] = True
							if label:
								dialog.AddControlToGrid(f'{control.name}_{item_num}_label',
								ControlType.label.value, label, row, column, expand=False)
								control_kwargs['colSpan'] = 1
								column += 1
							control_args = [f'{control.name}_{item_num}', control.type.value[:-1], *value, row, column, control.tooltip]
							control_items.append(dialog.AddRangeControlToGrid(*control_args, **control_kwargs))
							column += control_kwargs['colSpan']
					case ControlType.combo | ControlType.multilist:
						control_items.append(dialog.AddComboControlToGrid(*control_args, **control_kwargs))
					case _:
						control_items.append(dialog.AddControlToGrid(*control_args, **control_kwargs))
				
				if control.callback is not None:
					for control_item in control_items:
						control_item.ValueModified.connect(partial( control.callback, dialog ))
				column += 1

			row, column = row + 1, 0

		dialog.EndGrid()

		if in_group:
			dialog.EndGroupBox(isCollapsed=is_collapsed)

	#SubmitButton
	dialog.AddGrid()
	dialog.AddHorizontalSpacerToGrid('', 0, 0)
	submitButton = dialog.AddControlToGrid('submit_button', 'ButtonControl', 'Submit', 0, 1, expand=False)
	submitButton.ValueModified.connect(partial(submit_pressed, dialog))

	#CloseButton
	closeButton = dialog.AddControlToGrid('CloseButton', 'ButtonControl', 'Close', 0, 2, expand=False)
	closeButton.ValueModified.connect(dialog.closeEvent)
	dialog.EndGrid()

	dialog.setFixedHeight(dialog.sizeHint().height())

	toggle_enabled(dialog)
	files_selected(dialog)
	dialog.SetValue('file_paths_control', ';'.join(args))

	return dialog


def __main__(*args):
	if '--generate-options' in args:
		generate_options_file()

	modal = '--modal' in args  # Allows submission from terminal without window auto closing

	# filter out non-paths from args
	file_paths = [x for x in args if os.path.exists(x)]

	dialog = submission_dialog(*file_paths)

	# Quick and dirty way to stop the dialog being garbage collected
	# when opened from the Monitor
	if not modal:
		global script_dialog
		script_dialog = dialog

	dialog.ShowDialog(modal=modal)

