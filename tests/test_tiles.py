from __future__ import annotations

import pytest

pytest.importorskip("pyproj")

from roadsense import tiles  # noqa: E402

#: A real Digital Earth Africa item, measured 2026-10-29: proj:transform origin (672000, 1152000).
ITEM_ID = "67f3acdc-359f-54a1-814a-4a0fa7b965a9"
ITEM_ORIGIN = (672_000.0, 1_152_000.0)


def test_item_index_matches_a_real_stac_transform():
    # The item's transform origin is (672000, 1152000) — its *top-left* corner, because the
    # transform's y step is negative. Any point strictly inside therefore floors to (7, 11).
    assert tiles.item_id(ITEM_ORIGIN[0] + 1, ITEM_ORIGIN[1] - 1) == (7, 11)
    # Exactly on the top edge is a boundary case: it floors up into the item above. Callers use
    # Item.item_xy for item indices, which subtracts one item height first.
    assert tiles.item_id(*ITEM_ORIGIN) == (7, 12)


def test_point_inside_a_known_item_lands_in_it():
    x, y = tiles.to_ease(7.5, 9.45)
    assert tiles.item_id(x, y) == (7, 12)
    assert 672_000 <= x < 768_000


def test_to_ease_and_back_is_stable():
    lon, lat = 7.49, 9.06
    x, y = tiles.to_ease(lon, lat)
    back_lon, back_lat = tiles.to_wgs(x, y)
    assert abs(back_lon - lon) < 1e-9
    assert abs(back_lat - lat) < 1e-9


def test_tile_bounds_are_8km_and_aligned():
    left, bottom, right, top = tiles.tile_bounds(85, 150)
    assert right - left == 8_000
    assert top - bottom == 8_000
    assert left % 8_000 == 0 and bottom % 8_000 == 0


def test_tile_id_is_the_floor_of_the_metre_coordinate():
    assert tiles.tile_id(679_999, 1_200_000) == (84, 150)
    assert tiles.tile_id(680_000, 1_200_000) == (85, 150)


def test_corridor_tiles_counts_distinct_tiles():
    # Two points ~1.5 km apart inside the same 8 km tile should count once.
    found = tiles.corridor_tiles([[[7.49, 9.06], [7.50, 9.06]]])
    assert len(found) == 1


def test_corridor_tiles_spans_tiles_for_a_long_line():
    found = tiles.corridor_tiles([[[7.49, 9.06], [7.60, 9.06]]])
    assert len(found) >= 1


def test_tile_center_is_inside_the_tile():
    tx, ty = 85, 150
    lon, lat = tiles.tile_center_wgs(tx, ty)
    x, y = tiles.to_ease(lon, lat)
    assert tiles.tile_id(x, y) == (tx, ty)
