from __future__ import annotations

from pathlib import Path

from husk_submitter.options import OPTIONS, default_arguments, options_file_text

OPTIONS_FILE = Path(__file__).parents[1] / 'HuskStandalone' / 'HuskStandalone.options'


def test_options_file_matches_definitions() -> None:
	'''Regenerate with: python -m husk_submitter.options HuskStandalone/HuskStandalone.options'''
	assert OPTIONS_FILE.read_bytes().decode('utf-8') == options_file_text()


def test_default_arguments() -> None:
	arguments = default_arguments()

	assert arguments['--renderer'] == 'BRAY_HdKarmaXPU'
	assert arguments['override_--res'] == 'False'
	assert arguments['--res'] == '1920 1080'
	assert arguments['--disable-motionblur'] == 'False'
	assert 'override_--renderer' not in arguments
	assert len({option.flag for option in OPTIONS}) == len(OPTIONS)


def test_options_file_lists_settings_editable_after_submission() -> None:
	text = options_file_text()

	for key in ('[ExtraArguments]', '[Version]', '[RezRequest]', '[RezContext]'):
		assert key in text
	assert default_arguments()['ExtraArguments'] == ''
