from __future__ import annotations

import pytest

# Import guard first: roadsense.sampler imports rasterio at module level, and rasterio is an
# optional extra. Without this, a bare `.[dev]` install fails at collection instead of skipping.
pytest.importorskip("rasterio")
pytest.importorskip("pyproj")

import numpy as np  # noqa: E402

from roadsense import sampler  # noqa: E402


def test_s3_href_becomes_anonymous_https():
    href = "s3://deafrica-services/gm_s2_rolling/0-0-1/x188/y089/2024-01--P3M/a_B04.tif"
    assert sampler.s3_to_https(href) == (
        "https://deafrica-services.s3.af-south-1.amazonaws.com/"
        "gm_s2_rolling/0-0-1/x188/y089/2024-01--P3M/a_B04.tif"
    )


def test_https_href_is_left_alone():
    url = "https://example.com/a.tif"
    assert sampler.s3_to_https(url) == url


def test_item_xy_derives_from_the_transform_origin():
    item = sampler.Item(
        item_id="x",
        month="2024-01",
        assets={},
        transform=(10.0, 0.0, 672_000.0, 0.0, -10.0, 1_152_000.0, 0.0, 0.0, 1.0),
        shape=(9600, 9600),
    )
    assert item.item_xy == (7, 11)


def test_ndvi_and_ndbi_are_computed_from_the_bands():
    red = np.array([[1000.0, 2000.0]], dtype="float32")
    nir = np.array([[3000.0, 2000.0]], dtype="float32")
    swir = np.array([[4000.0, 2000.0]], dtype="float32")
    mask = np.array([[True, True]])
    out = sampler.indices(red, nir, swir, mask)

    assert out["ndvi_mean"] == pytest.approx((0.5 + 0.0) / 2)
    assert out["ndbi_mean"] == pytest.approx((0.14285714 + 0.0) / 2, abs=1e-6)
    assert out["pixels"] == 2
    assert out["pixels_valid"] == 2


def test_zero_nodata_pixels_are_excluded_not_averaged_in():
    # A (0, 0) pixel is "no observation" in GeoMAD, not a black road.
    red = np.array([[1000.0, 0.0]], dtype="float32")
    nir = np.array([[3000.0, 0.0]], dtype="float32")
    swir = np.array([[4000.0, 0.0]], dtype="float32")
    mask = np.array([[True, True]])
    out = sampler.indices(red, nir, swir, mask)

    assert out["pixels"] == 2
    assert out["pixels_valid"] == 1
    assert out["ndvi_mean"] == pytest.approx(0.5)


def test_all_invalid_returns_nan_rather_than_raising():
    zeros = np.zeros((2, 2), dtype="float32")
    out = sampler.indices(zeros, zeros, zeros, np.ones((2, 2), dtype=bool))
    assert out["pixels_valid"] == 0
    assert np.isnan(out["ndvi_mean"])


def test_road_mask_is_empty_for_no_paths():
    mask = sampler.road_mask([], 85, 150, resolution=40)
    assert mask.shape == (200, 200)
    assert not mask.any()


def test_rings_returns_a_core_and_a_disjoint_ring():
    from roadsense import tiles

    lon0, lat0 = tiles.to_wgs(681_000, 1_201_000)
    lon1, lat1 = tiles.to_wgs(687_000, 1_207_000)
    core, ring = sampler.rings([[[lon0, lat0], [lon1, lat1]]], 85, 150, resolution=10)

    assert core.shape == ring.shape == (800, 800)
    assert core.any() and ring.any()
    # The ring must exclude the carriageway, or the contrast is contaminated by tarmac.
    assert not (core & ring).any()


def test_ring_sits_further_out_than_the_core():
    from roadsense import tiles

    lon0, lat0 = tiles.to_wgs(684_000, 1_204_000)
    lon1, lat1 = tiles.to_wgs(684_000, 1_204_800)
    core, ring = sampler.rings([[[lon0, lat0], [lon1, lat1]]], 85, 150, resolution=10)

    # A vertical line through the tile centre: the ring must have pixels both left and right of
    # the core, while the core itself stays narrow.
    core_cols = np.where(core.any(axis=0))[0]
    ring_cols = np.where(ring.any(axis=0))[0]
    assert core_cols.max() - core_cols.min() <= 3
    assert ring_cols.min() < core_cols.min()
    assert ring_cols.max() > core_cols.max()


def test_rings_are_empty_without_paths():
    core, ring = sampler.rings([], 85, 150, resolution=40)
    assert not core.any() and not ring.any()


def test_contrast_is_ring_minus_core():
    assert sampler.contrast({"ndvi_mean": 0.10}, {"ndvi_mean": 0.35}) == pytest.approx(0.25)


def test_contrast_is_nan_when_either_side_is_missing():
    nan = float("nan")
    assert np.isnan(sampler.contrast({"ndvi_mean": 0.1}, {"ndvi_mean": nan}))
    assert np.isnan(sampler.contrast({"ndvi_mean": nan}, {"ndvi_mean": 0.3}))


def test_road_mask_marks_pixels_along_a_projected_line():
    # A short segment inside tile (85, 150); coordinates are lon/lat and must be projected.
    left, bottom = 680_000.0, 1_200_000.0
    from roadsense import tiles

    lon0, lat0 = tiles.to_wgs(left + 1000, bottom + 1000)
    lon1, lat1 = tiles.to_wgs(left + 7000, bottom + 7000)
    mask = sampler.road_mask([[[lon0, lat0], [lon1, lat1]]], 85, 150, resolution=40)

    assert mask.shape == (200, 200)
    assert mask.any()
    # The line runs corner to corner, so it must not flag the whole tile.
    assert mask.mean() < 0.3
