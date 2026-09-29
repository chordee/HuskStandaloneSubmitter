# Husk Standalone Submitter
A custom Deadline plugin and submitter script allowing direct submission of USD files to Husk for rendering.

Created by [Matt Tillman - Pixel Ninja](https://pixelninja.design/)

## Features:
- Submit multiple USD files
- Set frame range from stage
- Set renderer (Karma CPU or XPU)
- GPU affinity (for Karma XPU)
- Submit render passes (Houdini 21+)
- Override stage render settings during and after submission
- Path mapping of input and output files (untested)
- Submission of OutputFileNames to allow for easy checking/exploring from the Monitor

## Installation
### Copy Plugin Files
#### Install Script
Run the install.py script to copy the plugin and submission files to your repo.
Requires python 3 to be installed and the deadline bin directory to be in your path.

#### Manual
Copy the files to the following locations:

```
huskStandaloneSubmitter.py >
{ DeadlineRepository }/custom/scripts/Submission
```

```
HuskStandalone (DIR) >
{ DeadlineRepository }/custom/plugins/HuskStandalone
```

### Deadline Setup
In the Deadline Monitor go to:
Tools > Configure Plugin > HuskStandalone
Then set the husk executable of each Houdini version under Render Executables (e.g. **Houdini 21.0 Husk Executable**).
This should be:
`{Houdini Installation Directory}/bin/husk.exe`

Jobs render with the husk of the Houdini version they were submitted with. To support another version, add a `Houdini<major>_<minor>_Husk_Executable` entry to `HuskStandalone.param` and the version to `HOUDINI_VERSIONS` in `HuskStandaloneSubmission.py` and `python/husk_submitter/options.py`.

### Version Compatibility
Houdini 18+
Deadline 10

Certain settings only supported on newer Houdini versions (i.e. --pass is Houdini 21+). Tested on 20.5 and 21.

## Usage
### Deadline Monitor
Go to Submit > HuskStandalone

### Terminal/Script
`deadlinecommand ExecuteScript <path/to/HuskStandaloneSubmission.py> [usd_paths] --modal`

## Houdini Submitter (Houdini 21+)
A submitter that runs inside Houdini and reads USD with Houdini's own `pxr`, so render prims resolve exactly as husk sees them (same USD version, file format plugins and asset resolvers). It submits the same `HuskStandalone` plugin jobs, so the Deadline plugin setup above still applies, and it can be used alongside the Monitor submitter.

### Installation
1. Copy `houdini/husk_submitter.json` to a Houdini packages directory (e.g. `$HOUDINI_USER_PREF_DIR/packages`).
2. Edit `HUSK_SUBMITTER` in the copied file to point at this repository.
3. `deadlinecommand` must be found via `DEADLINE_PATH`, the macOS `/Users/Shared/Thinkbox/DEADLINE_PATH` file or `PATH`. This is the case on machines with the Deadline client installed.

### Usage
Add the **Husk Submitter** shelf, then click **Submit Husk**, or run from the Python shell:

```python
from husk_submitter import ui
ui.show()
```

Clicking **Submit...** parses the USD files and lists the jobs to be submitted with their outputs. Output paths written by more than one job are highlighted.

### Differences from the Monitor submitter
- Pass/Settings patterns use `*` wildcards against prim names, paths below `/Render` or absolute paths. A pattern that matches nothing is reported instead of silently falling back to the default settings.
- Job names are unique: prims sharing a name are labelled by their path below `/Render`, and duplicate file names get a numeric suffix.
- The running Houdini's version is written to the job, which selects the matching husk executable in **Configure Plugin**. Outside Houdini, and in the Monitor submitter, it is chosen with the **Houdini Version** setting.

### Development
The submitter core (`python/husk_submitter`: `render_info`, `jobs`, `deadline`, `options`) only depends on `pxr` and runs outside Houdini. Tests use [uv](https://docs.astral.sh/uv/) with `usd-core`:

```
uv run pytest
uv sync --group ui && uv run pytest   # also run the dialog tests (PySide6)
```

The husk arguments are defined once in `python/husk_submitter/options.py`. After changing them, regenerate the plugin options file:

`PYTHONPATH=python uv run python -m husk_submitter.options HuskStandalone/HuskStandalone.options`

## Notes
### Submission
Submission is mostly straightforward. Select your usd files, set the settings you want to override and click submit.

You can edit the settings of a running job in the monitor by right clicking on the job and selecting:
Modify Job Properties > HuskStandalone Settings.

### Determining Output Files
There is a bunch of logic that goes into determining the output files as `--pass`, `--settings` and `--output` all affect what gets rendered.

This is handled in the submission script but not in the plugin script itself so altering any of those options after submission will require manual intervention (i.e. `--pass` will not drive `--settings` and in turn `--settings` will not drive `--output`).

The basic outline is that RenderPasses can determine RenderSettings, which determine the RenderProducts which determine the ProductNames/Outputs. There can also be multiple passes/settings/products at each step.

### Render Passes
Most of the parameters mirror their husk arguments, with the notable exception of `--pass`. I have changed the submission implementation to match the useage of `--settings`. This allows for submitting multiple passes, the use of primnames instead of the full prim paths and pattern matching with * wildcards. 

As mentioned above; `--pass` will also drive `--settings` via the renderSource property.

I've suggested to SideFX that they implement this UX into Husk itself. It could just be me that wants this, but I find it hard to imagine a scenario where I have multiple render passes that don't each have their own corresponding settings/products.

### USD Parsing
All of this USD parsing is done via some very hacky regex on usdcat output for the sake of portability and minimising dependencies.

Using the proper USD python bindings would be much faster and more ergonomic but deadline is locked to python 3.10. This means it can't import the USD shipped with Houdini and would instead require a 3.10 compatible USD build/compile to be shipped with this script or be installed by users. That's not very portable so hacky regex it is.

### UI
The submission UI can be rearranged by reordering the rows of the CONTROLS variable.

To have changes reflected in the plugin options (i.e. when changing settings in the monitor after submission) regenerate the options file thusly:

`deadlinecommand ExecuteScript <path/to/HuskStandaloneSubmission.py> --generate-options`

## Changelog
### [2.0.0] - 2025-10-28
Major rewrite

## Thanks
Originally forked from and David Tree's Husk Submitter
https://github.com/DavidTree/HuskStandaloneSubmitter

