"""Build the corridor table — the modelling unit for this project.

Why corridors rather than segments:

1. **The data decides it.** GRID3 gives names to 869 distinct corridors covering 53,998 highway
   segments. The remaining 113,004 segments have no name and therefore no path to a label.
2. **The source speaks this language.** A procurement record names a corridor
   ("MAJOR MAINTENANCE OF OKWELLE-OJIAMA-IDEATO ROAD"), never a segment.
3. **A map of 869 corridors is legible.** A map of 167,002 segments is not.

Each corridor carries its geometry summary, its state span, and a count of known interventions.
"""

from __future__ import annotations

import re
from dataclasses import dataclass

import pandas as pd

from roadsense.states import normalise_state_name

#: Characters that cannot appear in an id.
_SLUG_STRIP = re.compile(r"[^a-z0-9]+")


def slugify(name: str) -> str:
    """Turn a corridor name into a stable identifier.

    Stable matters: these ids end up in feature tables, model outputs and the map, so a
    renaming upstream must not silently orphan a corridor's history. The slug is derived
    only from the name, so the same name always yields the same id.
    """
    slug = _SLUG_STRIP.sub("-", name.strip().lower()).strip("-")
    return slug or "unnamed"


@dataclass(frozen=True)
class CorridorSummary:
    corridor_id: str
    name: str
    n_segments: int
    length_km: float
    states: str
    primary_state: str
    primary_class: str
    lon: float
    lat: float
    label_events: int
    label_years: str


def build_corridors(segments: pd.DataFrame) -> pd.DataFrame:
    """Aggregate named segments into one row per corridor."""
    if "names" not in segments.columns:
        raise ValueError("segments table has no 'names' column")

    working = segments.copy()
    working["name"] = working["names"].fillna("").astype(str).str.strip()
    working = working[working["name"] != ""]
    working["length_m"] = pd.to_numeric(working["length_m"], errors="coerce").fillna(0.0)

    # Normalise here as well as at ingestion: an older cached segments table may carry the
    # raw boundary name ("Abuja Federal Capital Territory") instead of the canonical "FCT".
    working["state"] = working["state"].map(normalise_state_name)

    rows: list[dict] = []
    for name, group in working.groupby("name", sort=False):
        states = [s for s in group["state"].dropna().unique()]
        primary_state = (
            group["state"].value_counts().index[0] if group["state"].notna().any() else ""
        )
        primary_class = (
            group["road_class"].value_counts().index[0] if group["road_class"].notna().any() else ""
        )
        rows.append(
            {
                "corridor_id": slugify(name),
                "name": name,
                "n_segments": int(len(group)),
                "length_km": round(float(group["length_m"].sum()) / 1000.0, 3),
                "states": "|".join(sorted(states)),
                "primary_state": primary_state,
                "primary_class": primary_class,
                "lon": round(float(group["lon"].mean()), 6),
                "lat": round(float(group["lat"].mean()), 6),
                "label_events": 0,
                "label_years": "",
            }
        )

    corridors = pd.DataFrame(rows).sort_values("length_km", ascending=False).reset_index(drop=True)
    return corridors


def attach_labels(corridors: pd.DataFrame, matches: pd.DataFrame) -> pd.DataFrame:
    """Count high-confidence interventions per corridor and record the years they occurred."""
    high = matches[matches["confidence"] == "high"].copy()
    if high.empty:
        return corridors

    grouped = high.groupby("matched_name")
    events: dict[str, int] = grouped.size().to_dict()
    years: dict[str, list[int]] = {
        name: sorted({int(y) for y in frame["year"].dropna()})
        for name, frame in grouped
    }

    corridors = corridors.copy()
    corridors["label_events"] = corridors["name"].map(events).fillna(0).astype(int)
    corridors["label_years"] = corridors["name"].map(
        lambda name: "|".join(str(y) for y in years.get(name, []))
    )
    return corridors


def summarise(corridors: pd.DataFrame) -> dict:
    """Headline numbers for the corridors table."""
    labelled = corridors[corridors["label_events"] > 0]
    return {
        "corridors": int(len(corridors)),
        "total_km": round(float(corridors["length_km"].sum()), 1),
        "median_km": round(float(corridors["length_km"].median()), 2),
        "corridors_with_labels": int(len(labelled)),
        "corridors_with_repeat_labels": int((labelled["label_events"] > 1).sum()),
        "label_events_total": int(corridors["label_events"].sum()),
        "states_covered": len(
            {state for value in corridors["states"] for state in str(value).split("|") if state}
        ),
    }
