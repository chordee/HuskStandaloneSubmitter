#!/usr/bin/env python3
import os
import shlex
import subprocess

from Deadline.Plugins import DeadlinePlugin
from Deadline.Scripting import FileUtils, RepositoryUtils

# Husk arguments whose value is one argument, others are split on whitespace (eg. --res 1920 1080)
PATH_ARGUMENTS = ('--output', '--slap-comp')
CMD_SPECIAL_CHARACTERS = ' \t&|<>^()'


def cmd_quote(argument):
	'''
	Quote an argument for a cmd batch file, as rez runs commands in one.
	'''
	argument = argument.replace('%', '%%')
	if argument and not any(character in argument for character in CMD_SPECIAL_CHARACTERS):
		return argument
	# Double trailing backslashes so they don't escape the closing quote
	trailing = len(argument) - len(argument.rstrip('\\'))
	return '"{}{}"'.format(argument, '\\' * trailing)


def rez_arguments(husk_arguments, rez_context='', rez_request='', windows=os.name == 'nt'):
	'''
	rez arguments running husk with husk_arguments in a rez context file or package request.
	husk is passed as one command string for a fixed shell, with each argument quoted for
	that shell. Arguments after -- would be re-split and joined by rez for its default
	shell, which expands $F4 in PowerShell, %04d in cmd batch files and & in both.
	'''
	env = ['env', '--input', rez_context] if rez_context else ['env', *rez_request.split()]
	if windows:
		shell, command = 'cmd', ' '.join(cmd_quote(argument) for argument in ['husk', *husk_arguments])
	else:
		shell, command = 'bash', ' '.join(shlex.quote(argument) for argument in ['husk', *husk_arguments])
	return subprocess.list2cmdline([*env, '--shell', shell, '-c', command])


def GetDeadlinePlugin():
	return HuskStandalone()


def CleanupDeadlinePlugin(deadlinePlugin):
	deadlinePlugin.Cleanup()


class HuskStandalone(DeadlinePlugin):
	def __init__( self ):
		import sys
		if sys.version_info.major == 3:
			super().__init__()

		self.InitializeProcessCallback += self.InitializeProcess
		self.RenderExecutableCallback += self.RenderExecutable # get the renderExecutable Location
		self.RenderArgumentCallback += self.RenderArgument # get the arguments to go after the EXE


	def Cleanup( self ):
		del self.InitializeProcessCallback
		del self.RenderExecutableCallback
		del self.RenderArgumentCallback


	def InitializeProcess( self ):
		self.SingleFramesOnly=False
		self.StdoutHandling=True
		self.PopupHandling=False

		self.AddStdoutHandlerCallback('USD ERROR(.*)').HandleCallback += self.HandleStdoutError
		self.AddStdoutHandlerCallback( r'ALF_PROGRESS ([0-9]+(?=%))' ).HandleCallback += self.HandleStdoutProgress


	def RenderExecutable(self):
		# In a rez context husk is found on the context's PATH, see rez_arguments
		if any(self.RezSettings()):
			path_list = self.GetConfigEntryWithDefault('Rez_Executable', '')
			executable_path = FileUtils.SearchFileList(path_list)
			if not executable_path:
				self.FailRender('Failed to find the rez executable in Rez_Executable:\n{}'.format(path_list))
			return executable_path

		# Version is major.minor[.build], eg. 21.0.440 -> Houdini21_0_Husk_Executable
		version = self.GetPluginInfoEntryWithDefault( 'Version', '' )
		if not version:
			self.FailRender('No Houdini Version in the plugin info.')
		config_key = 'Houdini{}_Husk_Executable'.format('_'.join(version.split('.')[:2]))
		path_list = self.GetConfigEntryWithDefault(config_key, '')
		executable_path = FileUtils.SearchFileList(path_list)
		if not executable_path:
			self.FailRender('Failed to find the husk executable for Houdini {} in {}:\n{}'.format(version, config_key, path_list))
		return executable_path


	def RezSettings(self):
		'''
		The job's path mapped rez context file (.rxt) and package request, blank without rez.
		'''
		context = self.GetPluginInfoEntryWithDefault('RezContext', '')
		if context:
			context = RepositoryUtils.CheckPathMapping(context).replace('\\', '/')
		return context, self.GetPluginInfoEntryWithDefault('RezRequest', '')


	def RenderArgument( self ):
		'''
		Construct argument string to pass to Husk.
		'''
		usd_file_path = self.GetPluginInfoEntry('--usd-input')
		usd_file_path = RepositoryUtils.CheckPathMapping( usd_file_path )
		usd_file_path = usd_file_path.replace( '\\', '/' )

		frame = self.GetStartFrame()
		frame_count = self.GetEndFrame() - frame + 1

		arguments = [
			'--usd-input', usd_file_path, '--frame', str(frame),
			'--frame-count', str(frame_count), '--make-output-path']
		for arg_name in self.GetPluginInfoEntry('ArgumentList').split(';'):
			if arg_name == '--usd-input':
				continue

			if arg_name.startswith('override'):
				continue

			if not self.GetBooleanPluginInfoEntryWithDefault(f'override_{arg_name}', True):
				continue

			if arg_name == '--tile-count':
				arguments.append('--autotile')

			value = self.GetPluginInfoEntry(arg_name)

			# Map output paths
			if arg_name == '--output':
				value = ','.join(RepositoryUtils.CheckPathMapping(x).replace( '\\', '/' ) for x in value.split(','))

			if value == 'False' or value == '':
				continue
			elif value == 'True':
				arguments.append(arg_name)
			else:
				if arg_name == '--verbose':
					value += 'a'  # Required for progress handling
				arguments += [arg_name, *([value] if arg_name in PATH_ARGUMENTS else value.split())]

		self.LogInfo(f"Rendering USD file: {usd_file_path}")

		# Do GPU Affinity Environment vars
		if self.OverrideGpuAffinity():
			self.KarmaGPUAffinity()
			self.RedshiftGPUAffinity()

		rez_context, rez_request = self.RezSettings()
		if rez_context or rez_request:
			self.LogInfo('Rendering in rez: {}'.format(rez_context or rez_request))
			return rez_arguments(arguments, rez_context, rez_request)
		return subprocess.list2cmdline(arguments)


	def HandleStdoutProgress(self):
		self.SetStatusMessage(self.GetRegexMatch(0))
		self.SetProgress(float(self.GetRegexMatch(1)))


	def HandleStdoutError(self):
		self.FailRender(self.GetRegexMatch(0))


	def KarmaGPUAffinity(self):
		'''
		Set which GPUs to use using Karma Environment Variables
		More accurately disable which GPUs not to use
		Assumes max 4 GPUS
		'''
		MAX_GPUS = 4
		VAR_STRING_TEMPLATE = "KARMA_XPU_DISABLE_DEVICE_{}"

		selected_GPUs = list(self.GpuAffinity())
		self.LogInfo(f"Setting Karma GPUs {selected_GPUs}")

		for gpu in range(MAX_GPUS):
			if gpu in selected_GPUs:
				continue

			self.SetProcessEnvironmentVariable(VAR_STRING_TEMPLATE.format(gpu), "1")


	def RedshiftGPUAffinity(self):
		'''
		Set which GPUs to use using Redshift Environment Variable
		'''
		selected_GPUs = list(self.GpuAffinity())
		self.LogInfo(f"Setting Redshift GPUs {selected_GPUs}")
		self.SetProcessEnvironmentVariable('REDSHIFT_GPUDEVICES', ','.join([str(x) for x in selected_GPUs]))

