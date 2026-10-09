'''
Tests for the Deadline plugin's husk command, loaded with stub Deadline modules.
'''
from __future__ import annotations

import functools
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
	stubs['Deadline.Scripting'].FileUtils = None
	# Path mapping from //server to S:
	stubs['Deadline.Scripting'].RepositoryUtils = types.SimpleNamespace(
		CheckPathMapping=lambda path: path.replace('//server', 'S:'))
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


@pytest.mark.parametrize(('text', 'expected'), [
	('', []),
	('--threads 16  --purge-frame', ['--threads', '16', '--purge-frame']),
	('--log-file "D:/my logs/husk.log"', ['--log-file', 'D:/my logs/husk.log']),
	(r'--log-file C:\logs\husk.log', ['--log-file', r'C:\logs\husk.log']),
])
def test_split_arguments(plugin: types.ModuleType, text: str, expected: list[str]) -> None:
	assert plugin.split_arguments(text) == expected


def test_split_arguments_keeps_hashes(plugin: types.ModuleType) -> None:
	assert plugin.split_arguments('--log-file /render/shot#1.log --threads 16') == [
		'--log-file', '/render/shot#1.log', '--threads', '16']


@pytest.mark.parametrize('argument', ['x" & whoami & "', 'a\nwhoami', 'a\rb'])
def test_cmd_quote_rejects_what_cmd_cannot_pass(plugin: types.ModuleType, argument: str) -> None:
	with pytest.raises(ValueError):
		plugin.cmd_quote(argument)


def test_bash_passes_quotes_and_line_breaks(plugin: types.ModuleType) -> None:
	arguments = ['--log-file', 'x" & whoami & "', 'a\nb']
	command_line = plugin.rez_arguments(arguments, rez_request='houdini', windows=False)
	argv = rez_argv(command_line) if sys.platform == 'win32' else shlex.split(command_line)

	assert shlex.split(argv[5]) == ['husk', *arguments]


def test_split_arguments_unclosed_quote(plugin: types.ModuleType) -> None:
	with pytest.raises(ValueError):
		plugin.split_arguments('--log-file "D:/logs')


class FakeJobPlugin:
	'''Plugin info and task frames of a job, read through the DeadlinePlugin methods.'''

	def __init__(self, plugin_info: dict[str, str]) -> None:
		self.plugin_info = plugin_info
		self.failures: list[str] = []

	def GetPluginInfoEntry(self, key: str) -> str:
		return self.plugin_info[key]

	def GetPluginInfoEntryWithDefault(self, key: str, default: str) -> str:
		return self.plugin_info.get(key, default)

	def GetBooleanPluginInfoEntryWithDefault(self, key: str, default: bool) -> bool:
		return self.plugin_info.get(key, str(default)) == 'True'

	def GetStartFrame(self) -> int:
		return 1001

	def GetEndFrame(self) -> int:
		return 1005

	def LogInfo(self, message: str) -> None:
		pass

	def OverrideGpuAffinity(self) -> bool:
		return False

	def FailRender(self, message: str) -> None:
		self.failures.append(message)
		raise RuntimeError(message)


def render_argument(plugin: types.ModuleType, plugin_info: dict[str, str]) -> str:
	job = FakeJobPlugin(plugin_info)
	for name in ('RenderArgument', 'RezSettings'):
		setattr(job, name, getattr(plugin.HuskStandalone, name).__get__(job))
	return job.RenderArgument()


PLUGIN_INFO = {
	'ArgumentList': 'override_--res;--res;--verbose;override_--output;--output;--usd-input;ExtraArguments',
	'override_--res': 'True', '--res': '2048 858', '--verbose': '2',
	'override_--output': 'True', '--output': '//server/render/beauty.$F4.exr',
	'--usd-input': '//server/shots/shot010.usd', 'ExtraArguments': '--threads 16 --log-file "D:/my logs/husk.log"'}


def test_render_argument(plugin: types.ModuleType) -> None:
	argv = shlex.split(render_argument(plugin, PLUGIN_INFO))

	assert argv == [
		'--usd-input', 'S:/shots/shot010.usd', '--frame', '1001', '--frame-count', '5', '--make-output-path',
		'--res', '2048', '858', '--verbose', '2a', '--output', 'S:/render/beauty.$F4.exr',
		'--threads', '16', '--log-file', 'D:/my logs/husk.log']


def test_extra_arguments_added_after_submission(plugin: types.ModuleType) -> None:
	'''Modify Job Properties adds ExtraArguments to a job submitted without it in ArgumentList.'''
	plugin_info = dict(PLUGIN_INFO, ArgumentList='--usd-input', ExtraArguments='--purge-frame')

	assert render_argument(plugin, plugin_info).endswith('--make-output-path --purge-frame')


def test_render_argument_in_rez_context(plugin: types.ModuleType) -> None:
	plugin_info = dict(PLUGIN_INFO, ArgumentList='--usd-input', ExtraArguments='', RezContext='//server/ctx/shot010.rxt')

	assert render_argument(plugin, plugin_info).startswith('env --input S:/ctx/shot010.rxt --shell ')


def test_quotes_in_rez_on_windows_fail_the_render(plugin: types.ModuleType, monkeypatch: pytest.MonkeyPatch) -> None:
	'''A double quote kept by single quotes in Extra Arguments would end cmd's quoting.'''
	monkeypatch.setattr(plugin, 'rez_arguments', functools.partial(plugin.rez_arguments, windows=True))
	plugin_info = dict(PLUGIN_INFO, RezRequest='houdini', ExtraArguments="""--log-file 'x" & whoami & "'""")

	with pytest.raises(RuntimeError, match='Cannot render in rez'):
		render_argument(plugin, plugin_info)


def test_invalid_extra_arguments_fail_the_render(plugin: types.ModuleType) -> None:
	with pytest.raises(RuntimeError, match='Invalid ExtraArguments'):
		render_argument(plugin, dict(PLUGIN_INFO, ExtraArguments='--log-file "D:/logs'))
