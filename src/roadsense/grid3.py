"""Fetch road segments from the GRID3 NGA Roads v1.0 FeatureServer.

Only named highway segments matter for Gate G0: the label join is textual, and a segment
without a name cannot be joined. Measured 2026-10-28, that is 53,998 of the 167,002
highway segments — 32.3%. The rest are picked up later by corridor propagation.
"""

from __future__ import annotations

import json
from dataclasses import dataclass

import pandas as pd

from roadsense import config
from roadsense.io import fetch_json, quote


@dataclass(frozen=True)
class SegmentPage:
    features: list[dict]
    exceeded: bool


def _query_url(where: str, offset: int, page_size: int) -> str:
    params = {
        "where": where,
        "outFields": "id,names,class,road_surface,speed_estimate,Shape__Length",
        "returnGeometry": "true",
        # The service's native spatial reference is Web Mercator (102100). Without this the
        # coordinates come back in metres, which silently breaks every state lookup.
        "outSR": "4326",
        "geometryPrecision": "5",
        "resultOffset": str(offset),
        "resultRecordCount": str(page_size),
        "orderByFields": "OBJECTID ASC",
        "f": "json",
    }
    query = "&".join(f"{key}={quote(value)}" for key, value in params.items())
    return f"{config.GRID3_ROADS_URL}/query?{query}"


def count_segments(where: str) -> int:
    """Count segments matching ``where``."""
    params = f"where={quote(where)}&returnCountOnly=true&f=json"
    payload = fetch_json(f"{config.GRID3_ROADS_URL}/query?{params}")
    return int(payload["count"])


def fetch_segments(
    classes: tuple[str, ...] = config.HIGHWAY_CLASSES,
    *,
    require_name: bool = True,
    page_size: int = config.ARCGIS_PAGE_SIZE,
    max_pages: int | None = None,
) -> pd.DataFrame:
    """Download highway segments, paginating until exhausted.

    ``names IS NOT NULL`` is not sufficient: GRID3 stores an empty string for unnamed
    segments, so the filter must also exclude ``''`` or the count inflates to 167,002.
    """
    class_list = ", ".join(f"'{klass}'" for klass in classes)
    where = f"class IN ({class_list})"
    if require_name:
        where += " AND names <> ''"

    rows: list[dict] = []
    offset = 0
    page = 0
    while True:
        payload = fetch_json(_query_url(where, offset, page_size), timeout=180)
        features = payload.get("features", [])
        for feature in features:
            attributes = feature.get("attributes", {})
            lon, lat = _centroid(feature.get("geometry", {}))
            rows.append(
                {
                    "segment_id": attributes.get("id"),
                    "names": attributes.get("names"),
                    "road_class": attributes.get("class"),
                    "surface": attributes.get("road_surface"),
                    "speed_estimate": attributes.get("speed_estimate"),
                    "length_m": attributes.get("Shape__Length"),
                    "lon": lon,
                    "lat": lat,
                }
            )
        page += 1
        offset += page_size
        exceeded = bool(payload.get("exceededTransferLimit"))
        if not exceeded or not features:
            break
        if max_pages is not None and page >= max_pages:
            break

    return pd.DataFrame(rows)


def _centroid(geometry: dict) -> tuple[float | None, float | None]:
    """Mean of a polyline's vertices.

    Not a true centroid, and it does not need to be: it is only used to decide which state
    polygon contains the segment. GRID3 segments are short (median well under a kilometre),
    so the vertex mean sits comfortably inside the right state.
    """
    paths = geometry.get("paths") or []
    points = [pt for path in paths for pt in path]
    if not points:
        return None, None
    lon = sum(pt[0] for pt in points) / len(points)
    lat = sum(pt[1] for pt in points) / len(points)
    return round(lon, 6), round(lat, 6)


def load_boundaries(geojson_path) -> list:
    """Load ADM1 polygons for state assignment."""
    from roadsense.states import load_adm1

    return load_adm1(geojson_path)


def assign_states(segments: pd.DataFrame, polygons) -> pd.DataFrame:
    """Attach a state name to each segment from its centroid."""
    from roadsense.states import StateLocator, normalise_state_name

    locator = StateLocator(polygons)
    states = []
    for lon, lat in zip(segments["lon"], segments["lat"], strict=True):
        if lon is None or lat is None:
            states.append(None)
            continue
        found = locator.locate(lon, lat)
        states.append(normalise_state_name(found) if found else None)
    return segments.assign(state=states)


def save_segments(segments: pd.DataFrame, dest) -> None:
    """Persist segments as CSV (readable, diffable) alongside a small JSON summary."""
    dest.parent.mkdir(parents=True, exist_ok=True)
    segments.to_csv(dest, index=False)
    summary = {
        "rows": int(len(segments)),
        "by_class": segments["road_class"].value_counts().to_dict(),
        "missing_state": int(segments["state"].isna().sum()),
    }
    dest.with_suffix(".summary.json").write_text(json.dumps(summary, indent=2), encoding="utf-8")
