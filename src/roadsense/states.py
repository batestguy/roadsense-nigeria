"""Nigerian state names, aliases, and polygon lookup.

Two jobs:
1. Find a state name inside free-text procurement descriptions.
2. Decide which state a road segment falls in, from its centroid.

The second is what makes label matching trustworthy: a phrase like "MAINTENANCE OF
OKWELLE-OJIAMA-IDEATO ROAD" is only attributable if we know which state we are looking in.
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass
from pathlib import Path

#: Canonical state names, including the Federal Capital Territory.
STATES: tuple[str, ...] = (
    "Abia", "Adamawa", "Akwa Ibom", "Anambra", "Bauchi", "Bayelsa", "Benue", "Borno",
    "Cross River", "Delta", "Ebonyi", "Edo", "Ekiti", "Enugu", "FCT", "Gombe", "Imo",
    "Jigawa", "Kaduna", "Kano", "Katsina", "Kebbi", "Kogi", "Kwara", "Lagos", "Nasarawa",
    "Niger", "Ogun", "Ondo", "Osun", "Oyo", "Plateau", "Rivers", "Sokoto", "Taraba",
    "Yobe", "Zamfara",
)

#: Spellings and abbreviations that appear in real procurement text.
ALIASES: dict[str, tuple[str, ...]] = {
    "Akwa Ibom": ("akwa ibom", "akwa-ibom"),
    "Cross River": ("cross river", "cross-river"),
    "FCT": (
        "fct",
        "federal capital territory",
        "abuja federal capital territory",
        "abuja",
    ),
    "Nasarawa": ("nasarawa", "nassarawa", "nasawara"),
    "Niger": ("niger state", "niger"),
    "Yobe": ("yobe", "yobbe"),
    "Zamfara": ("zamfara", "zamfara state"),
    "Borno": ("borno", "bornu"),
    "Kaduna": ("kaduna",),
    "Kano": ("kano",),
}

#: Phrases that contain a state name but are not that state. Order matters.
FALSE_FRIENDS: tuple[str, ...] = (
    "niger delta",      # region, not Niger State
    "niger bridge",     # river crossing, not Niger State
    "delta state",
)

#: Precompiled alternation of every alias, longest first so "niger state" beats "niger".
_ALIAS_INDEX: list[tuple[str, str]] = sorted(
    (
        (alias, canonical)
        for canonical in STATES
        for alias in ALIASES.get(canonical, (canonical.lower(),))
    ),
    key=lambda pair: len(pair[0]),
    reverse=True,
)

_ALIAS_PATTERN = re.compile(
    r"\b(" + "|".join(re.escape(a) for a, _ in _ALIAS_INDEX) + r")\b",
    re.IGNORECASE,
)


def find_state(text: str) -> str | None:
    """Return the first Nigerian state named in ``text``, or ``None``.

    Longest-alias-first means "Niger State" is not mistaken for the word "Niger" in
    "Niger Delta", and the false-friend guard removes the remaining cases.
    """
    if not text:
        return None
    lowered = text.lower()

    for phrase in FALSE_FRIENDS:
        if phrase in lowered:
            # Mask the false friend so it cannot be matched as a state name.
            lowered = lowered.replace(phrase, " " * len(phrase))

    match = _ALIAS_PATTERN.search(lowered)
    if not match:
        return None
    alias = match.group(1).lower()
    for candidate_alias, canonical in _ALIAS_INDEX:
        if candidate_alias == alias:
            return canonical
    return None


# --- Geometry ----------------------------------------------------------------


def _iter_rings(geometry: dict) -> list[list[list[float]]]:
    """Flatten a GeoJSON Polygon or MultiPolygon into a list of rings."""
    if geometry["type"] == "Polygon":
        return geometry["coordinates"]
    if geometry["type"] == "MultiPolygon":
        return [ring for polygon in geometry["coordinates"] for ring in polygon]
    return []


def _bbox(rings: list[list[list[float]]]) -> tuple[float, float, float, float]:
    xs = [pt[0] for ring in rings for pt in ring]
    ys = [pt[1] for ring in rings for pt in ring]
    return min(xs), min(ys), max(xs), max(ys)


def _point_in_rings(x: float, y: float, rings: list[list[list[float]]]) -> bool:
    """Even-odd ray casting across all rings of one polygon (holes handled naturally)."""
    inside = False
    for ring in rings:
        for i in range(len(ring) - 1):
            x1, y1 = ring[i][0], ring[i][1]
            x2, y2 = ring[i + 1][0], ring[i + 1][1]
            if (y1 > y) != (y2 > y):
                x_cross = (x2 - x1) * (y - y1) / (y2 - y1) + x1
                if x < x_cross:
                    inside = not inside
    return inside


@dataclass(frozen=True)
class StatePolygon:
    name: str
    rings: list[list[list[float]]]
    bbox: tuple[float, float, float, float]


def _property_name(props: dict) -> str | None:
    for key in ("shapeName", "NAME_1", "st_name", "State", "state"):
        if key in props and props[key]:
            return str(props[key])
    return None


def load_adm1(path: Path) -> list[StatePolygon]:
    """Load an ADM1 GeoJSON file into polygon records."""
    payload = json.loads(path.read_text(encoding="utf-8"))
    polygons: list[StatePolygon] = []
    for feature in payload["features"]:
        name = _property_name(feature.get("properties", {}))
        if not name:
            continue
        rings = _iter_rings(feature["geometry"])
        if not rings:
            continue
        polygons.append(StatePolygon(name=name, rings=rings, bbox=_bbox(rings)))
    return polygons


class StateLocator:
    """Assigns a point to a state, with a bounding-box shortlist before exact testing."""

    def __init__(self, polygons: list[StatePolygon]) -> None:
        self.polygons = polygons

    def locate(self, lon: float, lat: float) -> str | None:
        for poly in self.polygons:
            minx, miny, maxx, maxy = poly.bbox
            if not (minx <= lon <= maxx and miny <= lat <= maxy):
                continue
            if _point_in_rings(lon, lat, poly.rings):
                return poly.name
        return None


def normalise_state_name(name: str | None) -> str | None:
    """Map a boundary dataset's state name onto our canonical spelling.

    Accepts ``None``/NaN so callers can map over a column without a NULL guard; note that
    ``float('nan')`` is truthy, which is exactly the trap this avoids.
    """
    if not isinstance(name, str):
        return None
    cleaned = name.strip()
    if not cleaned:
        return None
    for canonical in STATES:
        if cleaned.lower() == canonical.lower():
            return canonical
    for canonical, aliases in ALIASES.items():
        if cleaned.lower() in aliases:
            return canonical
    return cleaned
