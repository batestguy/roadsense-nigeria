"""Sample vegetation and built-up indices from Digital Earth Africa's GeoMAD COGs.

The design follows two measured facts from findings F2:

1. **A range read fetches a whole 8 km internal tile**, whatever the size of the area requested.
   So the unit of work is the tile, not the segment — one read serves every corridor in it.
2. **The 20 m overview is ~10× smaller per tile than 10 m**, and these reads are latency-bound, so
   the overview is both smaller and no slower. A 100 m road corridor is still 5 × 5 pixels at 20 m.

Two indices are computed per pixel neighbourhood:

* **NDVI** = (NIR − Red) / (NIR + Red) — vegetation vigour. Falling NDVI next to a road is the
  classic signal of deteriorating verge and dust encroachment.
* **NDBI** = (SWIR − NIR) / (SWIR + NIR) — built-up/bare dominance. Rising NDBI at a road pixel
  means exposed aggregate or laterite rather than canopy.

Neither is a road-condition measurement. They are *proxies for change*, and the model card has to
say so.
"""

from __future__ import annotations

import json
import time
from contextlib import contextmanager
from dataclasses import dataclass
from typing import Any

import numpy as np
import rasterio
from rasterio.features import rasterize
from rasterio.windows import Window

from roadsense import config, tiles

#: Bands needed: red and NIR for NDVI, SWIR for NDBI.
BANDS: tuple[str, ...] = ("B04", "B08", "B11")

#: Side of an 8 km tile in pixels at the native 10 m resolution.
NATIVE_PX = 800

#: Default analysis resolution, in metres. 10, or an available overview factor.
#:
#: Measured 2026-10-29, bytes per 8 km tile-band: **934 KB at 10 m, 857 KB at 20 m, 388 KB at
#: 40 m, 194 KB at 80 m**. The plan assumed 20 m would cost ~92 KB and be ~10× cheaper than 10 m;
#: it is 8% cheaper, because the overviews are stored as 256 px tiles and an 8 km footprint at
#: 20 m needs nine of them while the base image needs one (findings F16).
#:
#: 40 m is the default: 2.4× cheaper than 10 m, still ~2.5 pixels across a 100 m corridor, and
#: its 40 m pixel is a genuine 40 m average that includes the verge NDVI is supposed to measure.
#: Pass ``resolution=10`` for the fidelity run.
ANALYSIS_M = 40


@dataclass(frozen=True)
class Item:
    """One GeoMAD item: a 96 km tile-month, with its asset URLs in EPSG:6933."""

    item_id: str
    month: str
    assets: dict[str, str]
    transform: tuple[float, float, float, float, float, float]
    shape: tuple[int, int]

    @property
    def origin_x(self) -> float:
        return self.transform[2]

    @property
    def origin_y(self) -> float:
        return self.transform[5]

    @property
    def item_xy(self) -> tuple[int, int]:
        return int(self.origin_x // tiles.ITEM_M), int(
            (self.origin_y - tiles.ITEM_M) // tiles.ITEM_M
        )


def s3_to_https(href: str) -> str:
    """Rewrite an ``s3://bucket/key`` href to its anonymous HTTPS equivalent.

    The bucket is public and no requester-pays flag is set (findings F2), so no signing or
    credential of any kind is involved.
    """
    if href.startswith("s3://"):
        bucket, _, key = href[5:].partition("/")
        return f"https://{bucket}.s3.af-south-1.amazonaws.com/{key}"
    return href


def search(
    bbox: tuple[float, float, float, float],
    *,
    start: str | None = None,
    end: str | None = None,
    limit: int = 250,
) -> list[Item]:
    """Search the DE Africa STAC for GeoMAD items, following pagination.

    ``datetime`` filtering is done server-side; ``start``/``end`` are ISO dates.
    """
    items: list[Item] = []
    body: dict[str, Any] = {
        "collections": [config.GEOMAD_COLLECTION],
        "bbox": list(bbox),
        "limit": limit,
    }
    if start or end:
        body["datetime"] = f"{start or '..'}/{end or '..'}"

    url = f"{config.GEOMAD_STAC_URL}/search"
    next_body: dict[str, Any] | None = body

    while next_body is not None:
        payload = _post_json(url, next_body)
        for feature in payload.get("features", []):
            item = _to_item(feature)
            if item is not None:
                items.append(item)
        next_body = _next_body(payload)

    return items


def _next_body(payload: dict) -> dict | None:
    """Return the body needed to fetch the next page, or ``None`` when done.

    The API advertises a generic ``rel=search`` link on every response, so matching any link with
    rel ``search`` would loop forever. Only ``rel=next`` counts, and the response's own
    ``numberReturned``/``numberMatched`` is the fallback signal that the set is exhausted.
    """
    for link in payload.get("links", []):
        if link.get("rel") == "next" and link.get("body"):
            return link["body"]

    matched = payload.get("numberMatched")
    returned = payload.get("numberReturned")
    if matched is not None and returned is not None and int(returned) >= int(matched):
        return None
    if not payload.get("features"):
        return None
    return None


def _post_json(url: str, body: dict, *, attempts: int = 3) -> dict[str, Any]:
    """POST JSON and return the parsed response, retrying transient failures."""
    import urllib.request

    data = json.dumps(body).encode("utf-8")
    last_error: Exception | None = None

    for attempt in range(attempts):
        req = urllib.request.Request(
            url,
            data=data,
            headers={
                "Content-Type": "application/json",
                "Accept": "application/json",
                "User-Agent": "roadsense-ng/0.1 (+research project)",
            },
            method="POST",
        )
        try:
            with urllib.request.urlopen(req, timeout=90) as resp:
                return json.loads(resp.read().decode("utf-8"))
        except Exception as exc:  # noqa: BLE001 - retried below, re-raised after
            last_error = exc
            time.sleep(min(2**attempt, 8))

    raise RuntimeError(f"STAC search failed at {url}: {last_error}") from last_error


def _to_item(feature: dict) -> Item | None:
    props = feature.get("properties", {})
    transform = props.get("proj:transform")
    shape = props.get("proj:shape")
    start = props.get("start_datetime") or props.get("datetime")
    if not transform or not shape or not start:
        return None

    assets = {
        band: s3_to_https(asset["href"])
        for band, asset in feature.get("assets", {}).items()
        if band in BANDS and asset.get("href")
    }
    if not assets:
        return None

    return Item(
        item_id=feature["id"],
        month=str(start)[:7],
        assets=assets,
        transform=tuple(float(v) for v in transform[:6]),
        shape=(int(shape[0]), int(shape[1])),
    )


def index_by_tile(items: list[Item]) -> dict[tuple[int, int, str], Item]:
    """Key items by ``(item_x, item_y, month)`` so a tile lookup is a dict hit."""
    return {(*item.item_xy, item.month): item for item in items}


def road_mask(
    paths: list[list[list[float]]],
    tx: int,
    ty: int,
    *,
    resolution: int = ANALYSIS_M,
) -> np.ndarray:
    """Rasterise corridor lines onto an 8 km tile at the analysis resolution.

    ``all_touched=True`` matters: at 20 m a road is often a sub-pixel feature, and without it many
    corridors would rasterise to nothing at all. The mask is a *sampling region*, not a claim that
    every flagged pixel is tarmac — the corridor's 20 m pixels include the verge, which is exactly
    what NDVI should measure.
    """
    left, _, _, top = tiles.tile_bounds(tx, ty)
    size = tiles.TILE_M // resolution
    transform = rasterio.transform.from_origin(left, top, resolution, resolution)

    # The paths arrive in WGS84 degrees but the raster is in EPSG:6933 metres. Rasterising the
    # degrees directly against a metre transform silently produces an empty mask — every
    # coordinate lands within a pixel or two of the origin, far outside the window.
    shapes = [
        {
            "type": "LineString",
            "coordinates": [list(tiles.to_ease(lon, lat)) for lon, lat in path],
        }
        for path in paths
        if len(path) >= 2
    ]
    if not shapes:
        return np.zeros((size, size), dtype=bool)

    burned = rasterize(
        shapes,
        out_shape=(size, size),
        transform=transform,
        fill=0,
        default_value=1,
        all_touched=True,
        dtype="uint8",
    )
    return burned.astype(bool)


def overview_level(src: rasterio.DatasetReader, factor: int) -> int | None:
    """Index of the overview with this decimation factor, or ``None`` if absent.

    rasterio's ``overviews()`` lists factors ascending while GDAL's ``OVERVIEW_LEVEL`` open
    option indexes the same list in the order it stores them — which, measured on this product,
    is also ascending. Resolving the index from the file rather than hardcoding it keeps the
    sampler correct if a producer changes the pyramid.
    """
    factors = src.overviews(1)
    if factor in factors:
        return factors.index(factor)
    return None


@contextmanager
def open_band(url: str, *, resolution: int):
    """Open a band, positioned at the overview for ``resolution``.

    **Trap worth knowing:** asking for a *small* window at overview level 0 made GDAL fall back
    to downloading the entire 172 MB file (measured twice). Reading the full 8 km tile window
    costs 857 KB as expected. The sampler therefore always reads whole tiles, never fragments.
    """
    env = dict(
        GDAL_DISABLE_READDIR_ON_OPEN="EMPTY_DIR",
        GDAL_HTTP_MULTIPLEX="YES",
        CPL_VSIL_CURL_ALLOWED_EXTENSIONS=".tif",
        VSI_CACHE="FALSE",
    )
    factor = max(1, resolution // 10)
    with rasterio.Env(**env):
        if factor == 1:
            with rasterio.open(url) as src:
                yield src, 10.0
            return

        with rasterio.open(url) as probe:
            level = overview_level(probe, factor)
            available = probe.overviews(1)
        if level is None:
            raise ValueError(f"{url} has no {factor}x overview (available: {available})")
        with rasterio.open(url, overview_level=level) as src:
            yield src, float(src.transform.a)


def read_tile(
    item: Item,
    band: str,
    tx: int,
    ty: int,
    *,
    resolution: int = ANALYSIS_M,
    attempts: int = 3,
) -> np.ndarray:
    """Read one band of one 8 km tile at the requested resolution.

    Retries on transient network failures. At national scale a run makes ~145,000 reads, so a
    once-in-a-thousand timeout is certain to happen; without a retry it would kill an hours-long
    shard. Backoff is short because the failure mode is a stalled socket, not rate limiting.
    """
    left, _, _, top = tiles.tile_bounds(tx, ty)
    size = tiles.TILE_M // resolution
    last_error: Exception | None = None

    for attempt in range(attempts):
        try:
            with open_band(item.assets[band], resolution=resolution) as (src, res):
                window = Window(
                    (left - src.transform.c) / res, (src.transform.f - top) / res, size, size
                )
                return src.read(1, window=window).astype("float32")
        except Exception as exc:  # noqa: BLE001 - retried below, re-raised after
            last_error = exc
            time.sleep(min(2**attempt, 8))

    raise RuntimeError(
        f"failed to read {band} tile ({tx},{ty}) from {item.assets.get(band)}"
    ) from last_error


def _dilate(mask: np.ndarray, steps: int) -> np.ndarray:
    """Grow a boolean mask by ``steps`` pixels in the four cardinal directions.

    A 3×3 max filter would be more isotropic but costs nine comparisons per pixel; for a ring
    width of a few pixels on a 200 × 200 tile the difference is invisible and the four-way version
    is exact enough. Off-tile growth is clipped, which slightly narrows rings at tile edges.
    """
    out = mask.copy()
    for _ in range(max(0, steps)):
        grown = out.copy()
        grown[1:, :] |= out[:-1, :]
        grown[:-1, :] |= out[1:, :]
        grown[:, 1:] |= out[:, :-1]
        grown[:, :-1] |= out[:, 1:]
        out = grown
    return out


def rings(
    paths: list[list[list[float]]],
    tx: int,
    ty: int,
    *,
    resolution: int = ANALYSIS_M,
    core_m: int = 0,
    verge_inner_m: int = 50,
    verge_outer_m: int = 150,
) -> tuple[np.ndarray, np.ndarray]:
    """Two masks: the carriageway, and a verge band offset from it.

    Why: a pixel on a road centreline is mostly asphalt, so its NDVI is ≈ 0 whether the road is
    pristine or crumbling (findings F17). What separates a maintained corridor from a failing one
    is its edges — tidy verge and drainage versus encroaching dust, bare laterite and lost
    vegetation.

    Returns ``(core, ring)``. ``core`` is the centreline raster itself plus ``core_m`` metres of
    dilution; ``ring`` is the band between ``verge_inner_m`` and ``verge_outer_m`` from it, with
    the core's own footprint removed so the two never share a pixel and the contrast is not
    contaminated by tarmac.

    **An earlier version dilated the core into a 50 m "inner band" and called it the road.** At
    40 m that dilation is one pixel, which already spans ±40 m — so it sampled the road reserve
    rather than the carriageway, and the resulting contrast was negative by construction. The
    default is now an undilated centreline. Diluting it is still possible via ``core_m`` for a
    reserve-scale comparison, but it is no longer what "road" means.
    """
    size = tiles.TILE_M // resolution
    core = road_mask(paths, tx, ty, resolution=resolution)
    if not core.any():
        empty = np.zeros((size, size), dtype=bool)
        return empty, empty

    if core_m > 0:
        core = _dilate(core, max(1, round(core_m / resolution)))

    inner_px = max(1, round(verge_inner_m / resolution))
    outer_px = max(inner_px + 1, round(verge_outer_m / resolution))

    outer = _dilate(core, outer_px)
    hole = _dilate(core, inner_px)
    return core, outer & ~hole


def contrast(values: dict, ring: dict, key: str = "ndvi_mean") -> float:
    """Difference between the road band and its verge, in index units.

    Returns NaN when either side has no valid pixels. A positive value means the verge is greener
    than the carriageway — the normal, healthy case. A corridor where this shrinks towards zero is
    one where the vegetation beside the road has gone.
    """
    road_value = values.get(key, float("nan"))
    ring_value = ring.get(key, float("nan"))
    if road_value != road_value or ring_value != ring_value:  # NaN check without numpy warnings
        return float("nan")
    return float(ring_value - road_value)


def indices(red: np.ndarray, nir: np.ndarray, swir: np.ndarray, mask: np.ndarray) -> dict:
    """Mean NDVI and NDBI over the masked pixels of one tile.

    Division is done in float32 with the nodata cases removed first: GeoMAD uses 0 for "no
    observation", and 0/0 would otherwise produce NaN that silently poisons every downstream mean.
    """
    valid = mask & (nir + red != 0) & (swir + nir != 0)

    ndvi = np.full(red.shape, np.nan, dtype="float32")
    ndbi = np.full(red.shape, np.nan, dtype="float32")
    with np.errstate(divide="ignore", invalid="ignore"):
        ndvi[valid] = (nir[valid] - red[valid]) / (nir[valid] + red[valid])
        ndbi[valid] = (swir[valid] - nir[valid]) / (swir[valid] + nir[valid])

    total = int(mask.sum())
    usable = int(valid.sum())
    return {
        "pixels": total,
        "pixels_valid": usable,
        "ndvi_mean": float(np.nanmean(ndvi)) if usable else float("nan"),
        "ndbi_mean": float(np.nanmean(ndbi)) if usable else float("nan"),
        "red_mean": float(red[valid].mean()) if usable else float("nan"),
        "nir_mean": float(nir[valid].mean()) if usable else float("nan"),
        "swir_mean": float(swir[valid].mean()) if usable else float("nan"),
    }
