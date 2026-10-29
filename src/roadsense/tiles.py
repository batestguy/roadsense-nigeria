"""EASE-Grid 2.0 tile arithmetic — the grid Digital Earth Africa publishes on.

Why this exists rather than "just call rasterio": deciding *which* imagery to fetch is a pure
arithmetic question, and answering it without opening a file means the national coverage estimate
costs zero bytes. The sampler then uses the same tile ids, so what was counted is what gets read.

The grid, measured from a real STAC item on 2026-10-29:

* CRS is EPSG:6933 (EASE-Grid 2.0 Global).
* An item is 9600 px at 10 m = **96 km square**, aligned to multiples of 96,000 m.
* A COG internal tile is 800 px at 10 m = **8 km**, so one 96 km item holds exactly 12 × 12 of
  them, with no partial tiles.

Verified against item `9430270c-...`, whose `proj:transform` origin is `(672000, 1248000)` — i.e.
96 km tile `(7, 12)` — while `pyproj` maps a point inside that item's footprint to
`x=723,647, y=1,200,254`, hitting the same tile. Both agree, which is the check that the formula
below is not merely plausible.
"""

from __future__ import annotations

from pyproj import Transformer

#: Side of a Digital Earth Africa item, in metres (96 km).
ITEM_M = 96_000

#: Side of a COG internal tile, in metres (800 px at 10 m).
TILE_M = 8_000

_TO_EASE = Transformer.from_crs("EPSG:4326", "EPSG:6933", always_xy=True)
_TO_WGS = Transformer.from_crs("EPSG:6933", "EPSG:4326", always_xy=True)


def to_ease(lon: float, lat: float) -> tuple[float, float]:
    """Project WGS84 longitude/latitude to EPSG:6933 metres."""
    return _TO_EASE.transform(lon, lat)


def to_wgs(x: float, y: float) -> tuple[float, float]:
    """Project EPSG:6933 metres back to WGS84 longitude/latitude."""
    return _TO_WGS.transform(x, y)


def item_id(x: float, y: float) -> tuple[int, int]:
    """The 96 km item containing an EASE-Grid point."""
    return int(x // ITEM_M), int(y // ITEM_M)


def tile_id(x: float, y: float) -> tuple[int, int]:
    """The 8 km COG internal tile containing an EASE-Grid point."""
    return int(x // TILE_M), int(y // TILE_M)


def tile_bounds(tx: int, ty: int) -> tuple[float, float, float, float]:
    """``(left, bottom, right, top)`` of an 8 km tile, in EPSG:6933 metres."""
    left = tx * TILE_M
    bottom = ty * TILE_M
    return float(left), float(bottom), float(left + TILE_M), float(bottom + TILE_M)


def tile_center_wgs(tx: int, ty: int) -> tuple[float, float]:
    """Longitude/latitude of an 8 km tile's centre — for weather lookup and logging."""
    left, bottom, right, top = tile_bounds(tx, ty)
    return to_wgs((left + right) / 2.0, (bottom + top) / 2.0)


def corridor_tiles(paths: list[list[list[float]]]) -> set[tuple[int, int]]:
    """Every 8 km tile touched by a corridor's vertices.

    Vertex-level assignment is accurate enough here: GRID3's corridor geometry averages a vertex
    every ~68 m (270,949 vertices over 18,419 km), so a segment between two vertices cannot skip a
    whole 8 km tile. Densifying first would cost time and change nothing.
    """
    tiles: set[tuple[int, int]] = set()
    for path in paths:
        for lon, lat in path:
            x, y = to_ease(lon, lat)
            tiles.add(tile_id(x, y))
    return tiles
