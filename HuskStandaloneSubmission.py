import IntegrationUI
import re
import sys
import os
import mimetypes
import traceback
import glob

from System import Array
from System.Collections.Specialized import *
from System.IO import *
from System.Text import *
from System.Diagnostics import *
from collections import OrderedDict

from Deadline.Scripting import *

from DeadlineUI.Controls.Scripting.DeadlineScriptDialog import DeadlineScriptDialog

import imp
imp.load_source('IntegrationUI', RepositoryUtils.GetRepositoryFilePath(
    "submission/Integration/Main/IntegrationUI.py", True))

########################################################################
# Globals
########################################################################

########################################################################
# UH USD submitter
# V0.2 David Tree - davidtree.co.uk
########################################################################
scriptDialog = None
ProjectManagementOptions = None
settings = None
shotgunPath = None
startup = None
versionID = None
deadlineJobID = None

LoggingMap = OrderedDict({"None": 0,
                          "Basic": 1,
                          "Enhanced": 4,
                          "Godlike": 7,
                          "David": 9})

houdini_versions = ["18.5", "19.0", "19.5"]
houdini_renderers = ["Karma", "Arnold", "Redshift"]


def __main__(*args):
    SubmissionDialog().ShowDialog(False)


def GetSettingsFilename():
    return Path.Combine(GetDeadlineSettingsPath(), "CommandLineSettings.ini")


def SubmissionDialog():
    global scriptDialog
    global ProjectManagementOptions

    global settings
    global shotgunPath
    global startup
    global versionID
    global deadlineJobID

    scriptDialog = DeadlineScriptDialog()
    scriptDialog.SetTitle("Submit USD to Deadline")
    scriptDialog.SetIcon(scriptDialog.GetIcon('DraftPlugin'))

    scriptDialog.AddGrid()
    #	(	 	self, 	name, 	control, 	value, 	row, 	column, 	tooltip = "", 	expand = True, 	rowSpan = -1, 	colSpan = -1 )

    scriptDialog.AddControlToGrid("JobDescriptionSeparator", "SeparatorControl", "Job Description", 0, 0, colSpan=6)
    # JOB NAME
    scriptDialog.AddControlToGrid("NameLabel", "LabelControl", "Job Name", 1, 0,
                                  "The name of your job. This is optional, and if left blank, it will default to 'Untitled'.", False)
    scriptDialog.AddControlToGrid("NameBox", "TextControl", "Untitled", 1, 1, colSpan=5)
    # COMMENT Label
    scriptDialog.AddControlToGrid("CommentLabel", "LabelControl", "Comment", 2, 0,
                                  "A simple description of your job. This is optional and can be left blank.", False)
    scriptDialog.AddControlToGrid("CommentBox", "TextControl", "", 2, 1, colSpan=5)
    scriptDialog.EndGrid()

    scriptDialog.AddGrid()
    scriptDialog.AddControlToGrid("JobOptionsSeparator", "SeparatorControl", "Job Options", 0, 0, colSpan=3)
    scriptDialog.AddControlToGrid("PoolLabel", "LabelControl", "Pool", 1, 0,
                                  "The pool that your job will be submitted to.", False)
    scriptDialog.AddControlToGrid("PoolBox", "PoolComboControl", "none", 1, 1)
    scriptDialog.AddControlToGrid("GroupLabel", "LabelControl", "Group", 2, 0,
                                  "The group that your job will be submitted to.", False)
    scriptDialog.AddControlToGrid("GroupBox", "GroupComboControl", "none", 2, 1)
    scriptDialog.AddControlToGrid("PriorityLabel", "LabelControl", "Priority", 3, 0, "", False)
    scriptDialog.AddRangeControlToGrid("Priority", "RangeControl", 50, 0, 100, 0, 1, 3, 1)
    scriptDialog.EndGrid()

    scriptDialog.AddGrid()
    # file dialog
    scriptDialog.AddControlToGrid("InputOutputSeparator", "SeparatorControl", "Input Output", 0, 0, colSpan=8)
    scriptDialog.AddControlToGrid("InputLabel", "LabelControl", "USD File", 1,
                                  0, "The USD file you wish to render.", False)
    filesToProcess = scriptDialog.AddSelectionControlToGrid(
        "USDFilePath", "MultiFileBrowserControl", "", "USD Files (*.usd);;USDA Files (*.usda);;USDC Files(*.usdc);;USDZ Files(*.usdz)", 1, 1, colSpan=7)

    scriptDialog.AddControlToGrid("OutputFolderLabel", "LabelControl", "Output Folder", 5, 0, "", False)
    scriptDialog.AddSelectionControlToGrid("OutputFolder", "FolderBrowserControl", "", "", 5, 1, colSpan=7)
    scriptDialog.AddControlToGrid("OutputBaseNameLabel", "LabelControl", "BaseName", 6, 0, "", False)
    scriptDialog.AddControlToGrid("OutputBaseNameBox", "TextControl", "", 6, 1, colSpan=5)
    scriptDialog.AddControlToGrid("OutputExtendNameLabel", "LabelControl", "Ext", 6, 6, "", False)
    scriptDialog.AddComboControlToGrid("OutputExtendNameCombo", "ComboControl",
                                       "exr", ["exr", "png", "tif"], 6, 7, "", True)

    # Frame Boxes
    scriptDialog.AddControlToGrid("StartFrameLabel", "LabelControl", "Start Frame", 8, 0, "Start Frame", False)
    scriptDialog.AddRangeControlToGrid("StartFrame", "RangeControl", 1, -65535, 65535, 0, 1, 8, 1, "", True)
    scriptDialog.AddControlToGrid("EndFrameLabel", "LabelControl", "End Frame", 8, 2, "End Frame", False)
    scriptDialog.AddRangeControlToGrid("EndFrame", "RangeControl", 2, -65535, 65535, 0, 1, 8, 3, "", True)
    scriptDialog.AddControlToGrid("IncFrameLabel", "LabelControl", "inc", 8, 4, "Render every X frame", False)
    scriptDialog.AddRangeControlToGrid("IncFrame", "RangeControl", 1, 1, 100, 0, 1, 8, 5, "", True)
    scriptDialog.AddControlToGrid("PaddingFrameLabel", "LabelControl", "Padding", 8, 6, "", False)
    scriptDialog.AddRangeControlToGrid("PaddingFrame", "RangeControl", 4, 1, 10, 0, 1, 8, 7, "", True)
    scriptDialog.EndGrid()
    scriptDialog.AddGrid()
    scriptDialog.AddControlToGrid("HuskSettingSeparator", "SeparatorControl", "Husk Setting", 0, 0, colSpan=4)
    scriptDialog.AddControlToGrid("VersionLabel", "LabelControl", "Version", 2, 0, "", False)
    scriptDialog.AddComboControlToGrid("VersionCombo", "ComboControl", "19.5", houdini_versions, 2, 1, "", True)
    scriptDialog.AddControlToGrid("RendererLabel", "LabelControl", "Renderer", 2, 2, "", False)
    scriptDialog.AddComboControlToGrid("RendererCombo", "ComboControl", "Karma", houdini_renderers, 2, 3, "", True)
    scriptDialog.AddSelectionControlToGrid("HoudiniPackageDirCheckBox",
                                           "CheckBoxControl", False, "Houdini Package Dir", 9, 0, "", False)
    scriptDialog.AddSelectionControlToGrid(
        "HoudiniPackageDirFolder", "FolderBrowserControl", "", "", 9, 1, "", True, colSpan=3)

    scriptDialog.EndGrid()

    scriptDialog.AddGroupBox("OverideGroup", "Overide Setting", False)
    scriptDialog.AddGrid()
    scriptDialog.AddSelectionControlToGrid(
        "RenderSettingCheckBox", "CheckBoxControl", False, "Render Setting", 4, 0, "")
    scriptDialog.AddControlToGrid("RenderSettingBox", "TextControl", "", 4, 1, colSpan=5)

    scriptDialog.AddSelectionControlToGrid("CameraCheckBox", "CheckBoxControl", False, "Camera", 5, 0, "")
    scriptDialog.AddControlToGrid("CameraBox", "TextControl", "", 5, 1, colSpan=5)

    scriptDialog.AddSelectionControlToGrid("PurposeCheckBox", "CheckBoxControl", False, "Purpose", 6, 0, "")
    scriptDialog.AddControlToGrid("PurposeBox", "TextControl", "geometry,render", 6, 1, colSpan=5)

    scriptDialog.AddSelectionControlToGrid("ComplexityCheckBox", "CheckBoxControl", False, "Complexity", 7, 0, "")
    scriptDialog.AddControlToGrid("ComplexityBox", "TextControl", "veryhigh", 7, 1, colSpan=5)

    scriptDialog.AddSelectionControlToGrid("DisableMotionBlurCheckBox",
                                           "CheckBoxControl", False, "Disable Motion Blur", 8, 0, "")
    scriptDialog.AddSelectionControlToGrid("DisableLightingCheckBox",
                                           "CheckBoxControl", False, "Disable Lighting", 9, 0, "")
    scriptDialog.AddSelectionControlToGrid("CustomArgumentsCheckBox",
                                           "CheckBoxControl", False, "Custom Arguments", 10, 0, "")
    scriptDialog.AddControlToGrid("CustomArgumentsBox", "TextControl", "", 10, 1, colSpan=5)

    scriptDialog.EndGrid()
    scriptDialog.EndGroupBox(False)

    scriptDialog.AddGroupBox("ScriptsGroup", "Scripts Files", False)
    scriptDialog.AddGrid()

    scriptDialog.AddControlToGrid("PreRenderScriptLabel", "LabelControl", "Pre Render Script", 1, 0, "", False)
    scriptDialog.AddSelectionControlToGrid("PreRenderScriptBox", "FileBrowserControl",
                                           "", "Python Files (*.py)", 1, 1, colSpan=6)
    scriptDialog.AddControlToGrid("PreFrameScriptLabel", "LabelControl", "Pre Frame Script", 2, 0, "", False)
    scriptDialog.AddSelectionControlToGrid("PreFrameScriptBox", "FileBrowserControl",
                                           "", "Python Files (*.py)", 2, 1, colSpan=6)
    scriptDialog.AddControlToGrid("PostFrameScriptLabel", "LabelControl", "Post Frame Script", 3, 0, "", False)
    scriptDialog.AddSelectionControlToGrid("PostFrameScriptBox", "FileBrowserControl",
                                           "", "Python Files (*.py)", 3, 1, colSpan=6)
    scriptDialog.AddControlToGrid("PostRenderScriptLabel", "LabelControl", "Post Render Script", 4, 0, "", False)
    scriptDialog.AddSelectionControlToGrid("PostRenderScriptBox", "FileBrowserControl",
                                           "", "Python Files (*.py)", 4, 1, colSpan=6)

    scriptDialog.EndGrid()
    scriptDialog.EndGroupBox(False)

    # collapsed settings
    scriptDialog.AddGroupBox("AdvancedGroup", "Advanced Settings", False)
    scriptDialog.AddGrid()
    # Logging level
    scriptDialog.AddControlToGrid("LogLevelLabel", "LabelControl", "Log Level", 0, 0)
    scriptDialog.AddComboControlToGrid("LogLevelCombo", "ComboControl", "None", [
                                       "None", "Basic", "Enhanced", "Godlike", "David"], 0, 1)
    scriptDialog.EndGrid()
    scriptDialog.EndGroupBox(False)

    # SubmitButton
    scriptDialog.AddGrid()
    submitButton = scriptDialog.AddControlToGrid(
        "SubmitButton", "ButtonControl", "Submit", 0, 3, expand=False, colSpan=1)
    submitButton.ValueModified.connect(SubmitButtonPressed)
    # closeButton
    closeButton = scriptDialog.AddControlToGrid("CloseButton", "ButtonControl", "Close", 0, 4, expand=False, colSpan=1)
    closeButton.ValueModified.connect(scriptDialog.closeEvent)
    scriptDialog.EndGrid()

    # Load sticky settings
    settings = ("PoolBox", "GroupBox", "Priority", "USDFilePath",
                "OutputFolder", "OutputBaseNameBox", "OutputExtendNameCombo", "HoudiniPackageDirFolder", "RenderSettingBox", "CameraBox", "VersionCombo", "RendererCombo")
    scriptDialog.LoadSettings(GetSettingsFilename(), settings)
    scriptDialog.EnabledStickySaving(settings, GetSettingsFilename())

    return scriptDialog


def SubmitButtonPressed():
    # is file existing
    if not os.path.exists(scriptDialog.GetValue('USDFilePath')):
        scriptDialog.ShowMessageBox("USD file doesn't exist!", "Error")
        return

    if not scriptDialog.GetValue("EndFrame") > scriptDialog.GetValue("StartFrame"):
        scriptDialog.ShowMessageBox("End Frame must be higher than Start Frame", "Error")
        return

    # Create Job file
    jobInfoFilename = Path.Combine(GetDeadlineTempPath(), "usd_job_info.job")
    writer = StreamWriter(jobInfoFilename, False, Encoding.Unicode)
    writer.WriteLine("Plugin=HuskStandalone")
    writer.WriteLine("Name={}".format(scriptDialog.GetValue("NameBox")))
    writer.WriteLine("Comment={}".format(scriptDialog.GetValue("CommentBox")))
    writer.WriteLine("Priority={}".format(scriptDialog.GetValue("Priority")))
    writer.WriteLine("Pool={}".format(scriptDialog.GetValue("PoolBox")))
    writer.WriteLine("Group={}".format(scriptDialog.GetValue("GroupBox")))

    # if a framerange overide is not specified then just grab the nsi file range from the files
    if scriptDialog.GetValue("IncFrame") == 1:
        FrameList = "{0}-{1}".format(scriptDialog.GetValue("StartFrame"), scriptDialog.GetValue("EndFrame"))
    else:
        FrameList = ""
        i = scriptDialog.GetValue("StartFrame")
        while i < scriptDialog.GetValue("EndFrame"):
            if not i % scriptDialog.GetValue("IncFrame"):
                FrameList += ",{}".format(i)
            i += 1

    writer.WriteLine("Frames={}\n".format(FrameList))
    writer.Close()

    # Create plugin info file.
    pluginInfoFilename = Path.Combine(GetDeadlineTempPath(), "USD_plugin_info.job")
    writer = StreamWriter(pluginInfoFilename, False, Encoding.Unicode)
    writer.WriteLine("SceneFile={}".format(scriptDialog.GetValue("USDFilePath")))
    writer.WriteLine("LogLevel={}".format(scriptDialog.GetValue("LogLevelCombo")))
    writer.WriteLine("Renderer={}".format(scriptDialog.GetValue("RendererCombo")))
    writer.WriteLine("PreRenderScript={}".format(scriptDialog.GetValue("PreRenderScriptBox")))
    writer.WriteLine("PreFrameScript={}".format(scriptDialog.GetValue("PreFrameScriptBox")))
    writer.WriteLine("PostFrameScript={}".format(scriptDialog.GetValue("PostFrameScriptBox")))
    writer.WriteLine("PostRenderScript={}".format(scriptDialog.GetValue("PostRenderScriptBox")))
    writer.WriteLine("Version={}".format(scriptDialog.GetValue("VersionCombo")))
    writer.WriteLine("OutputFolder={}".format(scriptDialog.GetValue("OutputFolder")))
    writer.WriteLine("OutputBaseName={}".format(scriptDialog.GetValue("OutputBaseNameBox")))
    writer.WriteLine("OutputExtendName={}".format(scriptDialog.GetValue("OutputExtendNameCombo")))
    writer.WriteLine("PaddingFrame={}".format(scriptDialog.GetValue("PaddingFrameLabel")))

    if scriptDialog.GetValue("RenderSettingCheckBox"):
        writer.WriteLine("RenderSetting={}".format(scriptDialog.GetValue("RenderSettingBox")))
    if scriptDialog.GetValue("CameraCheckBox"):
        writer.WriteLine("Camera={}".format(scriptDialog.GetValue("CameraBox")))
    if scriptDialog.GetValue("DisableMotionBlurCheckBox"):
        writer.WriteLine("DisableMotionBlur={}".format(scriptDialog.GetValue("DisableMotionBlurCheckBox")))
        if scriptDialog.GetValue("DisableLightingCheckBox"):
            writer.WriteLine("DisableLighting={}".format(scriptDialog.GetValue("DisableLightingCheckBox")))
    if scriptDialog.GetValue("PurposeCheckBox"):
        writer.WriteLine("Purpose={}".format(scriptDialog.GetValue("PurposeBox")))
    if scriptDialog.GetValue("ComplexityCheckBox"):
        writer.WriteLine("Complexity={}".format(scriptDialog.GetValue("ComplexityBox")))
    if scriptDialog.GetValue("HoudiniPackageDirCheckBox"):
        writer.WriteLine("HoudiniPackageDir={}".format(scriptDialog.GetValue("HoudiniPackageDirFolder")))
    if scriptDialog.GetValue("CustomArgumentsCheckBox"):
        writer.WriteLine("CustomArguments={}".format(scriptDialog.GetValue("CustomArgumentsBox")))

    writer.Close()

    # Setup the command line arguments.
    arguments = StringCollection()

    arguments.Add(jobInfoFilename)
    arguments.Add(pluginInfoFilename)

    # Now submit the job.
    results = ClientUtils.ExecuteCommandAndGetOutput(arguments)
    scriptDialog.ShowMessageBox(results, "Submission Results")
