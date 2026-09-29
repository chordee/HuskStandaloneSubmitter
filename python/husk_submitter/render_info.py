'''
Read render prims and their relationships from a USD file with pxr.

Only the render root (/Render by default) is composed and payloads are not
loaded, so opening large shot files stays fast.
'''
from __future__ import annotations

import logging
import re
from dataclasses import dataclass, field
from pathlib import Path

from pxr import Usd, UsdRender

logger = logging.getLogger(__name__)

RENDER_ROOT = '/Render'
DIGITS_PATTERN = re.compile(r'\d+')


class RenderInfoError(Exception):
	'''Raised when a USD file cannot be read.'''


@dataclass
class RenderInfo:
	'''
	Render prims of a USD file.

	passes: RenderPass path -> renderSource RenderSettings path ('' if unset)
	settings: RenderSettings path -> RenderProduct paths
	products: RenderProduct path -> productName, animated frame numbers in printf format
	'''
	path: Path
	start_frame: int = 1
	end_frame: int = 1
	default_settings: str = ''
	passes: dict[str, str] = field(default_factory=dict)
	settings: dict[str, list[str]] = field(default_factory=dict)
	products: dict[str, str] = field(default_factory=dict)


def read_render_info(path: Path, render_root: str = RENDER_ROOT) -> RenderInfo:
	'''
	Open the USD file masked to render_root and collect its render prims.
	'''
	mask = Usd.StagePopulationMask([render_root])
	try:
		stage = Usd.Stage.OpenMasked(str(path), mask, Usd.Stage.LoadNone)
	except Exception as error:  # pxr raises Tf.ErrorException
		raise RenderInfoError(f'Failed to open {path}: {error}') from error
	if stage is None:
		raise RenderInfoError(f'Failed to open {path}')

	info = RenderInfo(path=path)
	info.start_frame, info.end_frame = _frame_range(stage)
	info.default_settings = stage.GetMetadata('renderSettingsPrimPath') or ''

	for prim in stage.Traverse():
		prim_path = str(prim.GetPath())
		if prim.IsA(UsdRender.Pass):
			targets = UsdRender.Pass(prim).GetRenderSourceRel().GetForwardedTargets()
			info.passes[prim_path] = str(targets[0]) if targets else ''
		elif prim.IsA(UsdRender.Settings):
			targets = UsdRender.Settings(prim).GetProductsRel().GetForwardedTargets()
			info.settings[prim_path] = [str(target) for target in targets]
		elif prim.IsA(UsdRender.Product):
			info.products[prim_path] = _product_name(UsdRender.Product(prim).GetProductNameAttr())

	return info


def _frame_range(stage: Usd.Stage) -> tuple[int, int]:
	'''
	Authored start and end timecodes, or 1-1 for a static stage.
	'''
	if not stage.HasAuthoredTimeCodeRange():
		return 1, 1
	return int(stage.GetStartTimeCode()), int(stage.GetEndTimeCode())


def _product_name(attribute: Usd.Attribute) -> str:
	'''
	Product name of a RenderProduct.
	Animated names have their frame number replaced with printf padding,
	static names are returned as authored.
	'''
	samples = attribute.GetTimeSamples()
	if not samples:
		return str(attribute.Get() or '')

	first = str(attribute.Get(samples[0]))
	if len(samples) > 1:
		pattern = _printf_from_pair(first, str(attribute.Get(samples[1])))
	else:
		pattern = _printf_from_frame(first, int(samples[0]))

	if pattern is None:
		logger.warning('Could not find frame number in productName %r', first)
		return first
	return pattern


def _printf_from_pair(first: str, second: str) -> str | None:
	'''
	Replace the digit run that differs between two consecutive frame names.
	'''
	first_runs = list(DIGITS_PATTERN.finditer(first))
	second_runs = list(DIGITS_PATTERN.finditer(second))
	if len(first_runs) != len(second_runs):
		return None

	for first_run, second_run in zip(first_runs, second_runs):
		if first_run.group() != second_run.group():
			return _replace_run(first, first_run, len(first_run.group()) != len(second_run.group()))
	return None


def _printf_from_frame(name: str, frame: int) -> str | None:
	'''
	Replace the last digit run matching the frame number.
	'''
	matches = [run for run in DIGITS_PATTERN.finditer(name) if int(run.group()) == frame]
	if not matches:
		return None
	return _replace_run(name, matches[-1], False)


def _replace_run(name: str, run: re.Match, unpadded: bool) -> str:
	width = len(run.group())
	padding = '%d' if unpadded or width == 1 else f'%0{width}d'
	return name[:run.start()] + padding + name[run.end():]
