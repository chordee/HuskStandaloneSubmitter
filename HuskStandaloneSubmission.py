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
imp.load_source( 'IntegrationUI', RepositoryUtils.GetRepositoryFilePath( "submission/Integration/Main/IntegrationUI.py", True ) )
import IntegrationUI

########################################################################
## Globals
########################################################################

########################################################################
## UH USD submitter
## V0.2 David Tree - davidtree.co.uk
########################################################################
scriptDialog = None
ProjectManagementOptions = None
settings = None
shotgunPath = None
startup = None
versionID = None
deadlineJobID = None

LoggingMap = OrderedDict({"None":0,
                          "Basic":1,
                          "Enhanced":4,
                          "Godlike":7,
                          "David":9})

def __main__( *args ):
    SubmissionDialog().ShowDialog( False )

def GetSettingsFilename():
    return Path.Combine( GetDeadlineSettingsPath(), "CommandLineSettings.ini" )

def SubmissionDialog():
    global scriptDialog
    global ProjectManagementOptions

    global settings
    global shotgunPath
    global startup
    global versionID
    global deadlineJobID

    scriptDialog = DeadlineScriptDialog()
    scriptDialog.SetTitle( "Submit USD to Deadline" )
    scriptDialog.SetIcon( scriptDialog.GetIcon( 'DraftPlugin' ) )

    scriptDialog.AddGrid()
    #	(	 	self, 	name, 	control, 	value, 	row, 	column, 	tooltip = "", 	expand = True, 	rowSpan = -1, 	colSpan = -1 )

    scriptDialog.AddControlToGrid( "JobOptionsSeparator", "SeparatorControl", "Job Description", 0, 0, colSpan=6 )
    # JOB NAME
    scriptDialog.AddControlToGrid( "NameLabel", "LabelControl", "Job Name", 1, 0, "The name of your job. This is optional, and if left blank, it will default to 'Untitled'.")
    scriptDialog.AddControlToGrid( "NameBox", "TextControl", "Untitled", 1, 1, colSpan=5 )
    # COMMENT Label
    scriptDialog.AddControlToGrid( "CommentLabel", "LabelControl", "Comment", 2, 0, "A simple description of your job. This is optional and can be left blank.", False )
    scriptDialog.AddControlToGrid( "CommentBox", "TextControl", "", 2, 1, colSpan=5 )
    scriptDialog.EndGrid()

    scriptDialog.AddGrid()
    scriptDialog.AddControlToGrid( "PoolLabel", "LabelControl", "Pool", 0, 0, "The pool that your job will be submitted to.", False )
    scriptDialog.AddControlToGrid( "PoolBox", "PoolComboControl", "none", 0, 1 )
    scriptDialog.AddControlToGrid( "GroupLabel", "LabelControl", "Group", 1, 0, "The group that your job will be submitted to.", False )
    scriptDialog.AddControlToGrid( "GroupBox", "GroupComboControl", "none", 1, 1 )
    scriptDialog.EndGrid()


    scriptDialog.AddGrid()
    #file dialog
    scriptDialog.AddControlToGrid( "InputLabel", "LabelControl", "USD File", 0, 0, "The USD file you wish to render.", False )
    filesToProcess = scriptDialog.AddSelectionControlToGrid( "USDFilePath", "MultiFileBrowserControl", "", "USD Files (*.usd);;USDA Files (*.usda);;USDC Files(*.usdc);;USDZ Files(*.usdz)", 0, 1, colSpan=5 )
    
    



    #Frame Boxes
    scriptDialog.AddControlToGrid( "StartFrameLabel", "LabelControl", "Start", 5, 0, "Start Frame", False )
    scriptDialog.AddRangeControlToGrid( "StartFrame", "RangeControl", 1,-65535,65535,0,1, 5,1 )
    scriptDialog.AddControlToGrid( "EndFrameLabel", "LabelControl", "End", 5, 2, "End Frame", False )
    scriptDialog.AddRangeControlToGrid( "EndFrame", "RangeControl", 2,-65535,65535,0,1, 5,3 )
    scriptDialog.AddControlToGrid( "IncFrameLabel", "LabelControl", "inc", 5, 4, "Render every X frame", False )
    scriptDialog.AddRangeControlToGrid( "IncFrame", "RangeControl", 1,1,100,0,1, 5, 5 )
    scriptDialog.EndGrid()

    scriptDialog.AddGroupBox("OverideGroup","Overide Setting",False)
    scriptDialog.AddGrid()
    scriptDialog.AddSelectionControlToGrid( "RenderSettingCheckbox", "CheckBoxControl", False, "Render Setting" ,6,0, "")
    scriptDialog.AddControlToGrid( "RenderSettingBox", "TextControl", "", 6, 1, colSpan=5)

    scriptDialog.AddSelectionControlToGrid( "CameraCheckbox", "CheckBoxControl", False, "Camera" ,7,0, "")
    scriptDialog.AddControlToGrid( "CameraBox", "TextControl", "", 7, 1, colSpan=5)

    scriptDialog.AddSelectionControlToGrid( "DisableMotionBlurCheckBox", "CheckBoxControl", False, "Disable Motion Blur" ,8,0, "")

    scriptDialog.EndGrid()
    scriptDialog.EndGroupBox(False)

    scriptDialog.AddGroupBox("ScriptsGroup","Scripts Files",False)
    scriptDialog.AddGrid()

    scriptDialog.AddControlToGrid( "PreRenderScriptLabel", "LabelControl", "Pre Render Script", 1, 0, "", False )
    scriptDialog.AddSelectionControlToGrid( "PreRenderScriptBox", "FileBrowserControl", "", "Python Files (*.py)", 1, 1, colSpan=6 )
    scriptDialog.AddControlToGrid( "PreFrameScriptLabel", "LabelControl", "Pre Frame Script", 2, 0, "", False )
    scriptDialog.AddSelectionControlToGrid( "PreFrameScriptBox", "FileBrowserControl", "", "Python Files (*.py)", 2, 1, colSpan=6 )
    scriptDialog.AddControlToGrid( "PostFrameScriptLabel", "LabelControl", "Post Frame Script", 3, 0, "", False )
    scriptDialog.AddSelectionControlToGrid( "PostFrameScriptBox", "FileBrowserControl", "", "Python Files (*.py)", 3, 1, colSpan=6 )
    scriptDialog.AddControlToGrid( "PostRenderScriptLabel", "LabelControl", "Post Render Script", 4, 0, "", False )
    scriptDialog.AddSelectionControlToGrid( "PostRenderScriptBox", "FileBrowserControl", "", "Python Files (*.py)", 4, 1, colSpan=6 )

    scriptDialog.EndGrid()
    scriptDialog.EndGroupBox(False)

    

    #collapsed settings
    scriptDialog.AddGroupBox("AdvancedGroup","Advanced Settings",False)
    scriptDialog.AddGrid()
    #Logging level
    scriptDialog.AddControlToGrid( "LogLevelLabel", "LabelControl", "Log Level", 0, 0)
    scriptDialog.AddComboControlToGrid("LogLevelCombo","ComboControl","None",["None","Basic","Enhanced","Godlike","David"],0,1)
    scriptDialog.EndGrid()
    scriptDialog.EndGroupBox(False)

    #SubmitButton
    scriptDialog.AddGrid()
    submitButton = scriptDialog.AddControlToGrid( "SubmitButton", "ButtonControl", "Submit", 0, 3, expand=False,colSpan=1 )
    submitButton.ValueModified.connect(SubmitButtonPressed)
    #closeButton
    closeButton = scriptDialog.AddControlToGrid( "CloseButton", "ButtonControl", "Close", 0, 4, expand=False, colSpan=1)
    closeButton.ValueModified.connect(scriptDialog.closeEvent)
    scriptDialog.EndGrid()

    #Load sticky settings
    #settings = ("DepartmentBox","PoolBox","SecondaryPoolBox","GroupBox","PriorityBox","IsBlacklistBox","MachineListBox","LimitGroupBox","DraftTemplateBox","InputBox","OutputDirectoryBox","OutputFileBox","FrameListBox")
    settings = ()
    scriptDialog.LoadSettings( GetSettingsFilename(), settings )
    scriptDialog.EnabledStickySaving( settings, GetSettingsFilename() )

    return scriptDialog

def SubmitButtonPressed():
    #is file existing
    if not os.path.exists(scriptDialog.GetValue('USDFilePath')):
        scriptDialog.ShowMessageBox( "USD file doesn't exist!", "Error" )
        return

    if not scriptDialog.GetValue("EndFrame") > scriptDialog.GetValue("StartFrame"):
        scriptDialog.ShowMessageBox( "End Frame must be higher than Start Frame", "Error" )
        return

    #Create Job file
    jobInfoFilename = Path.Combine( GetDeadlineTempPath(), "usd_job_info.job" )
    writer = StreamWriter( jobInfoFilename, False, Encoding.Unicode )
    writer.WriteLine( "Plugin=HuskStandalone" )
    writer.WriteLine( "Name={}".format(scriptDialog.GetValue( "NameBox" )))
    writer.WriteLine( "Comment={}".format(scriptDialog.GetValue( "CommentBox" )))


    # if a framerange overide is not specified then just grab the nsi file range from the files
    if scriptDialog.GetValue("IncFrame") == 1:
        FrameList = "{0}-{1}".format(scriptDialog.GetValue("StartFrame"),scriptDialog.GetValue("EndFrame"))
    else:
        FrameList = ""
        i = scriptDialog.GetValue("StartFrame")
        while i < scriptDialog.GetValue("EndFrame"):
            if not i % scriptDialog.GetValue("IncFrame"):
                FrameList += ",{}".format(i)
            i += 1

    writer.WriteLine( "Frames={}\n".format(FrameList))
    writer.Close()

    # Create plugin info file.
    pluginInfoFilename = Path.Combine( GetDeadlineTempPath(), "USD_plugin_info.job" )
    writer = StreamWriter( pluginInfoFilename, False, Encoding.Unicode )
    writer.WriteLine("SceneFile={}".format(scriptDialog.GetValue("USDFilePath")))
    writer.WriteLine("LogLevel={}".format(LoggingMap[scriptDialog.GetValue("LogLevelCombo")]))

    if scriptDialog.GetValue("RenderSettingCheckbox"):
        writer.WriteLine("RenderSetting={}".format(scriptDialog.GetValue("RenderSettingBox")))
    if scriptDialog.GetValue("CameraCheckbox"):
        writer.WriteLine("Camera={}".format(scriptDialog.GetValue("CameraBox")))
    if scriptDialog.GetValue("DisableMotionBlurCheckBox"):
        writer.WriteLine("DisableMotionBlur={}".format(scriptDialog.GetValue("DisableMotionBlurCheckBox")))

    writer.Close()

    # Setup the command line arguments.
    arguments = StringCollection()

    arguments.Add( jobInfoFilename )
    arguments.Add( pluginInfoFilename )

    # Now submit the job.
    results = ClientUtils.ExecuteCommandAndGetOutput( arguments )
    scriptDialog.ShowMessageBox( results, "Submission Results" )
