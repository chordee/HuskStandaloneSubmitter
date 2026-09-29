'''
Declarative definition of the husk arguments exposed by the submitter.

The same definitions drive the submitter UI, the plugin info written for each
job and the Deadline plugin's HuskStandalone.options file, so all three stay in
sync. Keys and value formats match what HuskStandalone.py expects.
'''
from __future__ import annotations

import sys
from dataclasses import dataclass
from enum import Enum
from pathlib import Path


class Kind(Enum):
	INT = 'int'
	INT2 = 'int2'
	TEXT = 'text'
	ENUM = 'enum'
	BOOL = 'bool'
	FILE_SAVE = 'file_save'


@dataclass(frozen=True)
class HuskOption:
	'''
	A husk command line argument.

	override: None for always-applied arguments, otherwise the default state
	of the enable toggle (plugin info key override_<flag>).
	'''
	flag: str
	label: str
	kind: Kind
	default: int | str | bool | tuple[int, int]
	group: str
	tooltip: str
	override: bool | None = None
	choices: tuple[str, ...] = ()
	minimum: int = 0
	maximum: int = 65535
	component_labels: tuple[str, str] = ('x', 'y')

	@property
	def override_key(self) -> str:
		return f'override_{self.flag}'

	def format_value(self, value: int | str | bool | tuple[int, int]) -> str:
		'''
		Format a value the way HuskStandalone.py parses plugin info entries.
		'''
		if self.kind is Kind.INT2:
			return f'{value[0]} {value[1]}'
		return str(value)


USD_INPUT_TOOLTIP = 'Select USD files to submit to Husk.\nSemicolon (;) separated list.'
USD_FILE_FILTER = 'USD Files (*.usd);;USDA Files (*.usda);;USDC Files(*.usdc);;USDZ Files(*.usdz)'

RENDERING = 'Rendering'
OVERRIDES = 'RenderSettingsOverrides'
USD = 'USD'
GROUPS = ('Submission', RENDERING, OVERRIDES, USD)

OPTIONS: tuple[HuskOption, ...] = (
	HuskOption(
		'--renderer', 'Renderer', Kind.ENUM, 'BRAY_HdKarmaXPU', RENDERING,
		'Specify Hydra client.',
		choices=('BRAY_HdKarmaXPU', 'BRAY_HdKarma', 'HdRedshiftRendererPlugin')),
	HuskOption(
		'--pixel-samples', 'Pixel Samples', Kind.INT, 128, RENDERING,
		'Enable to override samples per pixel.',
		override=False, minimum=1),
	HuskOption(
		'--pass', 'Pass Prim/s', Kind.TEXT, '', RENDERING,
		'Render using the RenderPass prim/s specified.\n'
		'Multiple render passes can be specified '
		'using a comma or space separated list and/or pattern matching.\n'
		'Custom submission implementation to match --settings UX.\n'
		'Each pass is submitted as a separate render job.',
		override=False),
	HuskOption(
		'--settings', 'Settings Prim/s', Kind.TEXT, '', RENDERING,
		'Render using the RenderSettings prim/s specified.\n'
		'Multiple render settings can be specified '
		'using a comma or space separated list and/or pattern matching.\n'
		'When disabled or blank defaults to either the RenderPass.renderSource '
		"(if --pass is set) or the layer's renderSettingsPrimPath metadata.",
		override=False),
	HuskOption(
		'--slap-comp', 'Slap Comp', Kind.TEXT, '', RENDERING,
		'Path to Apex COP .geo file to run on outputs.\n'
		'Options encoded using: path_to_graph?option=value&option2=value2.',
		override=False),
	HuskOption(
		'--tile-count', 'Auto Tile', Kind.INT2, (4, 4), RENDERING,
		'Enable autotiling, where Husk will render x by y tiles\n'
		'and stitch them together on completion.',
		override=False, minimum=1),
	HuskOption(
		'--verbose', 'Logging Verbosity', Kind.INT, 0, RENDERING,
		'Verbosity of rendering statistics.\n'
		'Note that verbose levels of 8 and greater may affect '
		'rendering performance and should only be used for debugging problem scenes.',
		maximum=9),
	HuskOption(
		'--res', 'Resolution', Kind.INT2, (1920, 1080), OVERRIDES,
		'Rendered image width and height, in pixels.',
		override=False),
	HuskOption(
		'--res-scale', 'Resolution Scale', Kind.INT, 100, OVERRIDES,
		'Scale the output image by the given percentage.',
		override=False, maximum=5000),
	HuskOption(
		'--camera', 'Camera', Kind.TEXT, '', OVERRIDES,
		'The primitive path of the camera to render from.',
		override=False),
	HuskOption(
		'--output', 'Output/s', Kind.FILE_SAVE, '', OVERRIDES,
		'Comma separated list of output image file paths.\n'
		'These can contain certain local variables:\n'
		'eg. $F/<F>/%d, $F4/<F4>/%04d, $FF/<FF>/%g\n'
		'Submitter tokens expanded per job:\n'
		'{usd} USD file name, {pass} RenderPass name, {settings} RenderSettings name',
		override=False),
	HuskOption(
		'--headlight', 'Headlight', Kind.ENUM, 'None', USD,
		'When there are no lights found on the stage,\n'
		'this controls the headlight mode.',
		override=True, choices=('None', 'Distant', 'Dome')),
	HuskOption(
		'--disable-scene-materials', 'Disable Scene Materials', Kind.BOOL, False, USD,
		'Disable all materials in the scene.\n'
		'This option applies to all render delegates.'),
	HuskOption(
		'--disable-scene-lights', 'Disable Scene Lights', Kind.BOOL, False, USD,
		'Disable all lights in the scene.\n'
		'This option applies to all render delegates.'),
	HuskOption(
		'--disable-motionblur', 'Disable Motion Blur', Kind.BOOL, False, USD,
		'Disable all lights in the scene.\n'
		'This option applies to all render delegates.'),
)


def default_arguments() -> dict[str, str]:
	'''
	Plugin info entries for every option at its default value.
	'''
	arguments = {}
	for option in OPTIONS:
		if option.override is not None:
			arguments[option.override_key] = str(option.override)
		arguments[option.flag] = option.format_value(option.default)
	return arguments


def options_file_text() -> str:
	'''
	Contents of the Deadline plugin's HuskStandalone.options file.
	'''
	lines = _usd_input_entry()
	index = 1
	for option in OPTIONS:
		category_order = GROUPS.index(option.group)
		if option.override is not None:
			lines += _override_entry(option, category_order, index)
			index += 1
		lines += _option_entry(option, category_order, index)
		index += 1
	return '﻿' + '\n'.join(lines) + '\n'


def _usd_input_entry() -> list[str]:
	return [
		'[--usd-input]', 'Category=Submission', 'CategoryOrder=0', 'Index=0',
		f'Description={USD_INPUT_TOOLTIP}', f'Filter={USD_FILE_FILTER}',
		'DefaultValue=', 'Type=Filename', 'Label=USD File/s', '']


def _override_entry(option: HuskOption, category_order: int, index: int) -> list[str]:
	return [
		f'[{option.override_key}]', f'Category={option.group}',
		f'CategoryOrder={category_order}', f'Index={index}',
		f'Description=Enables {option.flag} Husk option.',
		f'Label=Enable {option.label}', 'Type=Boolean',
		f'DefaultValue={option.override}', '']


def _option_entry(option: HuskOption, category_order: int, index: int) -> list[str]:
	lines = [
		f'[{option.flag}]', f'Category={option.group}',
		f'CategoryOrder={category_order}', f'Index={index}',
		f'Description={option.tooltip}']
	option_type = {
		Kind.INT: 'Integer', Kind.INT2: 'String', Kind.TEXT: 'String',
		Kind.ENUM: 'Enum', Kind.BOOL: 'Boolean', Kind.FILE_SAVE: 'FilenameSave'}[option.kind]

	if option.kind is Kind.FILE_SAVE:
		lines.append('Filter=')
	elif option.kind is Kind.INT:
		lines += [f'Minimum={option.minimum}', f'Maximum={option.maximum}', 'Increment=1']
	elif option.kind is Kind.ENUM:
		lines.append(f'Values={";".join(option.choices)}')

	lines += [
		f'DefaultValue={option.format_value(option.default)}',
		f'Type={option_type}', f'Label={option.label}', '']
	return lines


def main(argv: list[str]) -> None:
	'''
	Write the options file: python -m husk_submitter.options <HuskStandalone.options>
	'''
	Path(argv[1]).write_text(options_file_text(), encoding='utf-8', newline='\n')


if __name__ == '__main__':
	main(sys.argv)
