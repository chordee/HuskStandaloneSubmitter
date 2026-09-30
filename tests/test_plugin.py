'''
Tests for the Deadline plugin's husk command, loaded with stub Deadline modules.
'''
from __future__ import annotations

import shlex
import subprocess
import sys
import types
from pathlib import Path

import pytest

PLUGIN_DIRECTORY = Path(__file__).parents[1] / 'HuskStandalone'
HUSK_ARGUMENTS = [
	'--usd-input', 'D:/my shots/a&b.usd', '--frame', '1', '--make-output-path',
	'--output', 'D:/render/render.%04d.exr,D:/render/beauty.$F4.exr,D:/render/<F4>.exr',
	'--slap-comp', '//server/comp/graph.geo?foo=1&bar=2', '--res', '1920', '1080']


@pytest.fixture(scope='module')
def plugin() -> types.ModuleType:
	stubs = {name: types.ModuleType(name) for name in ('Deadline', 'Deadline.Plugins', 'Deadline.Scripting')}
	stubs['Deadline.Plugins'].DeadlinePlugin = object
	stubs['Deadline.Scripting'].FileUtils = stubs['Deadline.Scripting'].RepositoryUtils = None
	saved = {name: sys.modules.get(name) for name in stubs}
	sys.modules.update(stubs)
	sys.path.insert(0, str(PLUGIN_DIRECTORY))
	try:
		import HuskStandalone
		yield HuskStandalone
	finally:
		sys.path.remove(str(PLUGIN_DIRECTORY))
		sys.modules.pop('HuskStandalone', None)
		for name, module in saved.items():
			if module is None:
				sys.modules.pop(name, None)
			else:
				sys.modules[name] = module


@pytest.mark.parametrize(('argument', 'expected'), [
	('1920', '1920'),
	('render.%04d.exr', 'render.%%04d.exr'),
	('graph.geo?a=1&b=2', '"graph.geo?a=1&b=2"'),
	('D:/my shots/a.usd', '"D:/my shots/a.usd"'),
	('C:\\my dir\\', '"C:\\my dir\\\\"'),
	('', '""'),
])
def test_cmd_quote(plugin: types.ModuleType, argument: str, expected: str) -> None:
	assert plugin.cmd_quote(argument) == expected


def test_rez_request_on_windows(plugin: types.ModuleType) -> None:
	arguments = plugin.rez_arguments(['--output', 'D:/r/beauty.%04d.exr'], rez_request='houdini-21.0  ocio', windows=True)

	assert arguments == 'env houdini-21.0 ocio --shell cmd -c "husk --output D:/r/beauty.%%04d.exr"'


def test_rez_context_on_posix(plugin: types.ModuleType) -> None:
	arguments = plugin.rez_arguments(
		['--output', '/r/beauty.$F4.exr'], rez_context='/ctx/my shot.rxt', rez_request='ignored', windows=False)

	assert arguments == '''env --input "/ctx/my shot.rxt" --shell bash -c "husk --output '/r/beauty.$F4.exr'"'''


def rez_argv(command_line: str) -> list[str]:
	'''The arguments rez receives when a Worker launches it with command_line.'''
	script = 'import json, sys; print(json.dumps(sys.argv[1:]))'
	output = subprocess.run(f'"{sys.executable}" -c "{script}" {command_line}', capture_output=True, text=True, check=True)
	return __import__('json').loads(output.stdout)


@pytest.mark.skipif(sys.platform != 'win32', reason='runs a Windows command line')
def test_husk_receives_its_arguments_without_rez(plugin: types.ModuleType) -> None:
	assert rez_argv(subprocess.list2cmdline(HUSK_ARGUMENTS)) == HUSK_ARGUMENTS


@pytest.mark.skipif(sys.platform != 'win32', reason='runs cmd and a Windows command line')
def test_husk_receives_its_arguments_through_cmd(plugin: types.ModuleType, tmp_path: Path) -> None:
	'''
	Launch rez's arguments like a Worker does, then run the -c command in a batch file
	like rez's cmd shell does, with a fake husk printing the arguments it receives.
	'''
	argv = rez_argv(plugin.rez_arguments(HUSK_ARGUMENTS, rez_request='houdini', windows=True))
	assert argv[:4] == ['env', 'houdini', '--shell', 'cmd']
	(tmp_path / 'husk.bat').write_text(f'@"{sys.executable}" -c "import json, sys; print(json.dumps(sys.argv[1:]))" %*\n')
	(tmp_path / 'rez-shell.bat').write_text(f'@echo off\nset "PATH={tmp_path};%PATH%"\n{argv[5]}\n')

	output = subprocess.run(['cmd', '/c', str(tmp_path / 'rez-shell.bat')], capture_output=True, text=True, check=True)

	assert __import__('json').loads(output.stdout) == HUSK_ARGUMENTS


def test_husk_receives_its_arguments_through_bash(plugin: types.ModuleType) -> None:
	'''The bash command splits back into husk's arguments, after the Worker's command line parsing.'''
	command_line = plugin.rez_arguments(HUSK_ARGUMENTS, rez_request='houdini', windows=False)
	argv = rez_argv(command_line) if sys.platform == 'win32' else shlex.split(command_line)

	assert argv[:4] == ['env', 'houdini', '--shell', 'bash']
	assert shlex.split(argv[5]) == ['husk', *HUSK_ARGUMENTS]
