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
    """Aggregate named segments into one row per corridor.

    Grouped by slug rather than by raw name, because GRID3 spells one road many ways:
    "Airport Road", "Airport road" and "AIRPORT ROAD" are three names for one corridor, as are
    "Benin-Sagamu Expressway" and "Benin - Sagamu Expressway". Measured on the real network,
    grouping by raw name produced 869 rows over 850 distinct slugs — 18 ids used twice, which
    made ``corridor_id`` non-unique and broke the feature-table merge (the duplicate check saw
    one corridor written by two names and refused to merge).

    The spelling with the most segments supplies the display ``name``; the others are kept in
    ``aliases`` so geometry and labels can still be joined through them.
    """
    if "names" not in segments.columns:
        raise ValueError("segments table has no 'names' column")

    working = segments.copy()
    working["name"] = working["names"].fillna("").astype(str).str.strip()
    working = working[working["name"] != ""]
    working["length_m"] = pd.to_numeric(working["length_m"], errors="coerce").fillna(0.0)
    working["corridor_id"] = working["name"].map(slugify)

    # Normalise here as well as at ingestion: an older cached segments table may carry the
    # raw boundary name ("Abuja Federal Capital Territory") instead of the canonical "FCT".
    working["state"] = working["state"].map(normalise_state_name)

    rows: list[dict] = []
    for corridor_id, group in working.groupby("corridor_id", sort=False):
        # Rank spellings by how much of the road uses them, so the display name is the one the
        # data actually prefers rather than whichever sorts first.
        stats = group.groupby("name")["length_m"].agg(segments="size", metres="sum")
        ranked = sorted(
            stats.index,
            key=lambda variant: (
                -int(stats.at[variant, "segments"]),
                -float(stats.at[variant, "metres"]),
                variant,
            ),
        )
        name = ranked[0]
        aliases = sorted(ranked[1:])

        states = [s for s in group["state"].dropna().unique()]
        primary_state = (
            group["state"].value_counts().index[0] if group["state"].notna().any() else ""
        )
        primary_class = (
            group["road_class"].value_counts().index[0] if group["road_class"].notna().any() else ""
        )
        rows.append(
            {
                "corridor_id": corridor_id,
                "name": name,
                "aliases": "|".join(aliases),
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


def _alias_column(corridors: pd.DataFrame) -> pd.Series:
    """The ``aliases`` column, or empty strings for a table built before it existed.

    ``str(float('nan'))`` is the string "nan", and NaN is truthy, so the emptiness check has to
    be explicit rather than ``value or ""``.
    """
    if "aliases" not in corridors.columns:
        return pd.Series([""] * len(corridors), index=corridors.index, dtype=object)
    return corridors["aliases"].map(lambda value: "" if pd.isna(value) else str(value))


def alias_map(corridors: pd.DataFrame) -> dict[str, str]:
    """Every GRID3 spelling of a corridor name -> that corridor's ``corridor_id``.

    Needed because geometry and label matches arrive keyed by the raw name, and a variant
    spelling no longer has its own row in the corridor table.
    """
    mapping: dict[str, str] = {}
    for corridor_id, name, aliases in zip(
        corridors["corridor_id"], corridors["name"], _alias_column(corridors), strict=True
    ):
        mapping[str(name)] = str(corridor_id)
        for variant in aliases.split("|"):
            if variant:
                mapping[variant] = str(corridor_id)
    return mapping


def merge_paths_by_corridor(
    corridors: pd.DataFrame, paths_by_name: dict[str, list[list[list[float]]]]
) -> dict[str, list[list[list[float]]]]:
    """Re-key raw-name geometry onto corridor display names, folding in variant spellings.

    Without this, merging variants would silently drop the geometry of whichever spelling lost
    the vote for display name — e.g. 2 segments of "wudil potiskum Federal Road" next to 457 of
    "Wudil - Potiskum Federal Road" would vanish from the map and from tile counting.
    """
    merged: dict[str, list[list[list[float]]]] = {}
    for name, aliases in zip(corridors["name"], _alias_column(corridors), strict=True):
        names = [str(name)] + [variant for variant in aliases.split("|") if variant]
        group = [path for variant in names for path in paths_by_name.get(variant, [])]
        if group:
            merged[str(name)] = group
    return merged


def attach_labels(corridors: pd.DataFrame, matches: pd.DataFrame) -> pd.DataFrame:
    """Count high-confidence interventions per corridor and record the years they occurred.

    Joined on the slug of the matched name, not on the name itself, so an event that names a
    variant spelling still lands on the corridor that owns it.
    """
    high = matches[matches["confidence"] == "high"].copy()
    if high.empty:
        return corridors

    high["corridor_id"] = high["matched_name"].astype(str).map(slugify)
    grouped = high.groupby("corridor_id")
    events: dict[str, int] = grouped.size().to_dict()
    years: dict[str, list[int]] = {
        corridor_id: sorted({int(y) for y in frame["year"].dropna()})
        for corridor_id, frame in grouped
    }

    corridors = corridors.copy()
    corridors["label_events"] = corridors["corridor_id"].map(events).fillna(0).astype(int)
    corridors["label_years"] = corridors["corridor_id"].map(
        lambda corridor_id: "|".join(str(y) for y in years.get(corridor_id, []))
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
