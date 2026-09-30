from __future__ import annotations

from pathlib import Path

import pytest

from conftest import make_stage
from husk_submitter.render_info import RenderInfoError, read_cameras, read_render_info


def test_reads_render_prims(shot_usd: Path) -> None:
	info = read_render_info(shot_usd)

	assert (info.start_frame, info.end_frame) == (1001, 1010)
	assert info.default_settings == '/Render/rs_beauty'
	assert info.passes == {'/Render/pass_fg': '/Render/rs_beauty', '/Render/pass_bg': '/Render/rs_beauty'}
	assert info.settings['/Render/rs_beauty'] == ['/Render/Products/beauty', '/Render/Products/depth']
	assert info.products == {
		'/Render/Products/beauty': '/out/beauty.%04d.exr',
		'/Render/Products/depth': '/out/depth.%04d.exr',
		'/Render/Products/util': '/out/util.exr',
	}


@pytest.mark.parametrize(('samples', 'expected'), [
	({9: '/o/a.9.exr', 10: '/o/a.10.exr'}, '/o/a.%d.exr'),
	({1001: '/o/v1001/a.1001.exr'}, '/o/v1001/a.%04d.exr'),
	({1001: '/o/v002/a_0999.exr', 1002: '/o/v002/a_1000.exr'}, '/o/v002/a_%04d.exr'),
	({1001: '/o/still.exr', 1002: '/o/still.exr'}, '/o/still.exr'),
])
def test_animated_product_names(tmp_path: Path, samples: dict[float, str], expected: str) -> None:
	path = make_stage(
		tmp_path / 'anim.usda',
		products={'/Render/Products/p': samples},
		settings={'/Render/rs': ['/Render/Products/p']})

	assert read_render_info(path).products['/Render/Products/p'] == expected


def test_only_render_root_is_read(tmp_path: Path) -> None:
	path = make_stage(
		tmp_path / 'masked.usda',
		products={'/Render/Products/p': '/o/p.exr'},
		settings={'/Render/rs': ['/Render/Products/p'], '/Elsewhere/rs': []})

	assert list(read_render_info(path).settings) == ['/Render/rs']


def test_static_stage_frame_range(tmp_path: Path) -> None:
	path = make_stage(tmp_path / 'static.usda', products={}, settings={'/Render/rs': []}, frame_range=None)

	assert (read_render_info(path).start_frame, read_render_info(path).end_frame) == (1, 1)


def test_unreadable_file(tmp_path: Path) -> None:
	path = tmp_path / 'broken.usda'
	path.write_text('not usd')

	with pytest.raises(RenderInfoError):
		read_render_info(path)
	with pytest.raises(RenderInfoError):
		read_cameras(path)


def test_reads_cameras_outside_render_root(shot_usd: Path) -> None:
	assert read_cameras(shot_usd) == ['/cameras/main', '/cameras/closeup']
