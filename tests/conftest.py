from __future__ import annotations

from pathlib import Path

import pytest
from pxr import Sdf, Usd, UsdRender


def make_stage(
		path: Path,
		products: dict[str, str | dict[float, str]],
		settings: dict[str, list[str]],
		passes: dict[str, str] | None = None,
		default_settings: str = '',
		frame_range: tuple[int, int] | None = (1001, 1010)) -> Path:
	'''
	Author a USD file with render prims.
	products values are a static productName or {time: productName} samples.
	'''
	stage = Usd.Stage.CreateNew(str(path))
	if frame_range:
		stage.SetStartTimeCode(frame_range[0])
		stage.SetEndTimeCode(frame_range[1])
	if default_settings:
		stage.SetMetadata('renderSettingsPrimPath', default_settings)

	for prim_path, name in products.items():
		attribute = UsdRender.Product.Define(stage, prim_path).CreateProductNameAttr()
		if isinstance(name, dict):
			for time, value in name.items():
				attribute.Set(value, time)
		else:
			attribute.Set(name)

	for prim_path, targets in settings.items():
		UsdRender.Settings.Define(stage, prim_path).CreateProductsRel().SetTargets([Sdf.Path(t) for t in targets])

	for prim_path, source in (passes or {}).items():
		render_pass = UsdRender.Pass.Define(stage, prim_path)
		if source:
			render_pass.CreateRenderSourceRel().SetTargets([Sdf.Path(source)])

	stage.GetRootLayer().Save()
	return path


@pytest.fixture
def shot_usd(tmp_path: Path) -> Path:
	'''
	Two passes sharing a settings prim, a utility settings prim and animated products.
	'''
	return make_stage(
		tmp_path / 'shot_v001.usda',
		products={
			'/Render/Products/beauty': {1001: '/out/beauty.1001.exr', 1002: '/out/beauty.1002.exr'},
			'/Render/Products/depth': {1001: '/out/depth.1001.exr', 1002: '/out/depth.1002.exr'},
			'/Render/Products/util': '/out/util.exr',
		},
		settings={
			'/Render/rs_beauty': ['/Render/Products/beauty', '/Render/Products/depth'],
			'/Render/rs_util': ['/Render/Products/util'],
		},
		passes={
			'/Render/pass_fg': '/Render/rs_beauty',
			'/Render/pass_bg': '/Render/rs_beauty',
		},
		default_settings='/Render/rs_beauty')
