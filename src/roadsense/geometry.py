"""Corridor geometry — one MultiLineString per named corridor, for the map.

The segment table built for Gate G0 keeps only a centroid per segment, because textual
matching does not need the shape. The map does. This module refetches the same named
segments with their full paths and merges them by name, so a corridor is drawn as the
continuous line it actually is rather than as 60 unconnected stubs.

**Memory note:** paths are accumulated per corridor as pages arrive instead of building one
big DataFrame first. 53,998 segments of raw JSON is roughly 400 MB of Python objects; the
merged result is a tenth of that. Streaming per page keeps the peak flat.
"""

from __future__ import annotations

import json
from pathlib import Path

import pandas as pd

from roadsense import config
from roadsense.io import fetch_json, quote

#: Coordinates are written at 5 decimal places (~1.1 m), which is finer than the source
#: network's positional accuracy and cuts file size against 6 dp.
COORD_PRECISION = 5


def _page_url(where: str, offset: int, page_size: int) -> str:
    params = {
        "where": where,
        "outFields": "id,names,class,Shape__Length",
        "returnGeometry": "true",
        "outSR": "4326",
        # Geometry arrives at full precision; it is rounded once on the way out.
        "geometryPrecision": "6",
        "resultOffset": str(offset),
        "resultRecordCount": str(page_size),
        "orderByFields": "OBJECTID ASC",
        "f": "json",
    }
    query = "&".join(f"{key}={quote(value)}" for key, value in params.items())
    return f"{config.GRID3_ROADS_URL}/query?{query}"


def collect_corridor_paths(
    classes: tuple[str, ...] = config.HIGHWAY_CLASSES,
    *,
    page_size: int = config.ARCGIS_PAGE_SIZE,
    max_pages: int | None = None,
) -> dict[str, list[list[list[float]]]]:
    """Download named highway geometry and group the paths by corridor name.

    Returns ``{name: [path, ...]}`` where each path is a list of ``[lon, lat]`` pairs.
    Duplicated paths are dropped: GRID3 splits a long road into many segments and some
    repeats appear after simplification on their side.
    """
    class_list = ", ".join(f"'{klass}'" for klass in classes)
    where = f"class IN ({class_list}) AND names <> ''"

    paths: dict[str, list[list[list[float]]]] = {}
    seen: dict[str, set[tuple[tuple[float, float], ...]]] = {}

    offset = 0
    page = 0
    while True:
        payload = fetch_json(_page_url(where, offset, page_size), timeout=180)
        features = payload.get("features", [])
        for feature in features:
            name = (feature.get("attributes", {}).get("names") or "").strip()
            if not name:
                continue
            for raw_path in feature.get("geometry", {}).get("paths") or []:
                if len(raw_path) < 2:
                    continue
                path = [[round(pt[0], 6), round(pt[1], 6)] for pt in raw_path]
                key = tuple((pt[0], pt[1]) for pt in path)
                bucket = seen.setdefault(name, set())
                if key in bucket:
                    continue
                bucket.add(key)
                paths.setdefault(name, []).append(path)

        page += 1
        if not payload.get("exceededTransferLimit") or not features:
            break
        if max_pages is not None and page >= max_pages:
            break
        offset += page_size

    return paths


def perpendicular_distance(point, start, end) -> float:
    """Distance from ``point`` to the segment ``start``-``end``, in degrees.

    Degrees are not metres, but this is only used to decide which vertices a map can
    afford to lose, and at these latitudes the distortion is a constant factor.
    """
    (px, py), (ax, ay), (bx, by) = point, start, end
    dx, dy = bx - ax, by - ay
    if dx == 0 and dy == 0:
        return ((px - ax) ** 2 + (py - ay) ** 2) ** 0.5
    t = ((px - ax) * dx + (py - ay) * dy) / (dx * dx + dy * dy)
    t = max(0.0, min(1.0, t))
    return ((px - (ax + t * dx)) ** 2 + (py - (ay + t * dy)) ** 2) ** 0.5


def simplify(points: list[list[float]], tolerance: float) -> list[list[float]]:
    """Ramer–Douglas–Peucker simplification, iterative to avoid recursion limits.

    A 300 km corridor can carry several thousand vertices. At a 10 m tolerance most of
    those are collinear or near-collinear and contribute nothing a screen can show.
    """
    if len(points) < 3 or tolerance <= 0:
        return list(points)

    keep = [False] * len(points)
    keep[0] = keep[-1] = True
    stack = [(0, len(points) - 1)]

    while stack:
        first, last = stack.pop()
        if last <= first + 1:
            continue
        worst, worst_index = 0.0, first
        for index in range(first + 1, last):
            distance = perpendicular_distance(points[index], points[first], points[last])
            if distance > worst:
                worst, worst_index = distance, index
        if worst > tolerance:
            keep[worst_index] = True
            stack.append((first, worst_index))
            stack.append((worst_index, last))

    return [point for point, kept in zip(points, keep, strict=True) if kept]


def simplify_all(
    paths: list[list[list[float]]], tolerance: float
) -> list[list[list[float]]]:
    """Simplify every path, dropping any that collapse below two points."""
    result = []
    for path in paths:
        reduced = simplify(path, tolerance)
        if len(reduced) >= 2:
            result.append(reduced)
    return result


def _bbox(paths: list[list[list[float]]]) -> list[float]:
    lons = [point[0] for path in paths for point in path]
    lats = [point[1] for path in paths for point in path]
    return [
        round(min(lons), COORD_PRECISION),
        round(min(lats), COORD_PRECISION),
        round(max(lons), COORD_PRECISION),
        round(max(lats), COORD_PRECISION),
    ]


def build_feature_collection(
    corridors: pd.DataFrame,
    paths_by_name: dict[str, list[list[list[float]]]],
    *,
    tolerance: float = 0.0001,
) -> dict:
    """Join the corridor table to its paths and produce a GeoJSON FeatureCollection.

    Corridors present in the table but absent from ``paths_by_name`` are skipped with a
    note in the returned ``missing`` list rather than silently vanishing from the map.
    """
    features: list[dict] = []
    missing: list[str] = []
    total_vertices = 0

    for row in corridors.itertuples(index=False):
        raw = paths_by_name.get(row.name)
        if not raw:
            missing.append(row.name)
            continue

        paths = simplify_all(raw, tolerance)
        if not paths:
            missing.append(row.name)
            continue

        rounded = [
            [[round(pt[0], COORD_PRECISION), round(pt[1], COORD_PRECISION)] for pt in path]
            for path in paths
        ]
        total_vertices += sum(len(path) for path in rounded)

        features.append(
            {
                "type": "Feature",
                "id": row.corridor_id,
                "properties": {
                    "corridor_id": row.corridor_id,
                    "name": row.name,
                    "primary_state": row.primary_state,
                    "states": row.states,
                    "road_class": row.primary_class,
                    "length_km": float(row.length_km),
                    "n_segments": int(row.n_segments),
                    "label_events": int(row.label_events),
                    "label_years": str(row.label_years),
                    "n_parts": len(rounded),
                    "bbox": _bbox(rounded),
                },
                "geometry": {"type": "MultiLineString", "coordinates": rounded},
            }
        )

    return {
        "type": "FeatureCollection",
        "name": "roadsense-ng-corridors",
        "features": features,
        "missing": missing,
        "total_vertices": total_vertices,
    }


def write_feature_collection(fc: dict, dest: Path) -> Path:
    """Write a FeatureCollection without the bookkeeping keys, which GeoJSON rejects."""
    dest.parent.mkdir(parents=True, exist_ok=True)
    payload = {
        "type": "FeatureCollection",
        "name": fc.get("name", "roadsense"),
        "features": fc["features"],
    }
    dest.write_text(
        json.dumps(payload, separators=(",", ":"), ensure_ascii=False), encoding="utf-8"
    )
    return dest
