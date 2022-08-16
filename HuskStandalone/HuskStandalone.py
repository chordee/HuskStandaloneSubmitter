#!/usr/bin/env python3

from System import *
from System.Diagnostics import *
from System.IO import *

import os

from Deadline.Plugins import *
from Deadline.Scripting import *

from pathlib import Path


def GetDeadlinePlugin():
    return HuskStandalone()


def CleanupDeadlinePlugin(deadlinePlugin):
    deadlinePlugin.Cleanup()


class HuskStandalone(DeadlinePlugin):
    # functions inside a class must be indented in python - DT
    def __init__(self):
        self.InitializeProcessCallback += self.InitializeProcess
        self.RenderExecutableCallback += self.RenderExecutable  # get the renderExecutable Location
        self.RenderArgumentCallback += self.RenderArgument  # get the arguments to go after the EXE

    def Cleanup(self):
        del self.InitializeProcessCallback
        del self.RenderExecutableCallback
        del self.RenderArgumentCallback

    def InitializeProcess(self):
        self.SingleFramesOnly = True
        self.StdoutHandling = True
        self.PopupHandling = False

        self.AddStdoutHandlerCallback("USD ERROR(.*)").HandleCallback += self.HandleStdoutError  # detect this error
        self.AddStdoutHandlerCallback(r"ALF_PROGRESS ([0-9]+(?=%))").HandleCallback += self.HandleStdoutProgress

    # get path to the executable
    def RenderExecutable(self):
        version = self.GetPluginInfoEntry("Version")
        return self.GetConfigEntry("USD_RenderExecutable_" + version.replace(".", "_"))

    # get the settings that go after the filename in the render command, 3Delight only has simple options.
    def RenderArgument(self):

        # construct fileName
        # this will only support 1 frame per task

        usdFile = self.GetPluginInfoEntry("SceneFile")
        usdFile = RepositoryUtils.CheckPathMapping(usdFile)
        usdFile = usdFile.replace("\\", "/")

        usdPaddingLength = FrameUtils.GetPaddingSizeFromFilename(usdFile)

        frameNumber = self.GetStartFrame()  # check this 2021 USD
        renderer = self.GetPluginInfoEntry("Renderer")
        pre_render_script = self.GetPluginInfoEntry("PreRenderScript")
        pre_frame_script = self.GetPluginInfoEntry("PreFrameScript")
        post_frame_script = self.GetPluginInfoEntry("PostFrameScript")
        post_render_script = self.GetPluginInfoEntry("PostRenderScript")

        camera = self.GetPluginInfoEntryWithDefault("Camera", "")
        render_setting = self.GetPluginInfoEntryWithDefault("RenderSetting", "")
        purpose = self.GetPluginInfoEntryWithDefault("Purpose", "")
        complexity = self.GetPluginInfoEntryWithDefault("Complexity", "")
        output_folder = self.GetPluginInfoEntry("OutputFolder")
        output_folder = RepositoryUtils.CheckPathMapping(output_folder)
        output_folder = output_folder.replace("\\", "/")
        if output_folder.endswith("/"):
            output_folder = output_folder[:-1]
        
        output_base_name = self.GetPluginInfoEntry("OutputBaseName").replace("\\", "/")
        output_ext_name = self.GetPluginInfoEntry("OutputExtendName")
        padding_frame = self.GetIntegerPluginInfoEntry("PaddingFrame")
        custom_arguments = padding_frame = self.GetPluginInfoEntryWithDefault("CustomArguments", "")

        argument = ""
        argument += usdFile + " "

        if camera:
            argument += "--camera {} ".format(camera)
        if render_setting:
            argument += '--settings {} '.format(render_setting)

        argument += "--renderer {} ".format(renderer)

        if self.GetBooleanPluginInfoEntry("DisableLighting"):
            argument += "--disable-lighting "
        if self.GetBooleanPluginInfoEntry("DisableMotionBlur"):
            argument += "--disable-motionblur "

        if purpose:
            argument += "--purpose {} ".format(purpose)
        if complexity:
            argument += "--complexity {} ".format(complexity)

        if pre_render_script:
            argument += "--prerender-script {} ".format(pre_render_script)
        if pre_frame_script:
            argument += "--preframe-script {} ".format(pre_frame_script)
        if post_frame_script:
            argument += "--postframe-script {} ".format(post_frame_script)
        if post_render_script:
            argument += "--postrender-script {} ".format(post_render_script)

        if custom_arguments:
            argument += custom_arguments + ' '

        argument += "--verbose a{} ".format(self.GetPluginInfoEntry("LogLevel")
                                            )  # alfred style output and full verbosity

        argument += "--frame {} ".format(frameNumber)

        argument += "--frame-count 1" + " "  # only render 1 frame per task

        # renderer handled in job file.
        # [:-4] We are now going to site the composite USD in the project root.

        paddedFrameNumber = StringUtils.ToZeroPaddedString(frameNumber, padding_frame)
        argument += "-o {0}/{1}.{2}.{3} ".format(output_folder, output_base_name, paddedFrameNumber, output_ext_name)
        argument += " --make-output-path" + " "

        houdini_package_dir = self.GetPluginInfoEntryWithDefault("HoudiniPackageDir", "")
        if houdini_package_dir:
            self.SetEnvironmentVariable("HOUDINI_PACKAGE_DIR", houdini_package_dir.replace("\\", "/"))

        self.LogInfo("Rendering USD file: " + usdFile)
        return argument

    # just incase we want to implement progress at some point
    def HandleStdoutProgress(self):
        self.SetStatusMessage(self.GetRegexMatch(0))
        self.SetProgress(float(self.GetRegexMatch(1)))

    # what to do when an error is detected.
    def HandleStdoutError(self):
        self.FailRender(self.GetRegexMatch(0))
