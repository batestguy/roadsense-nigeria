"""Turn the raw Nigeria OCDS export into typed maintenance-intervention records.

The source is a general procurement dataset, not a road-condition register. Most of the work
is therefore *exclusion*: deciding what is genuinely a maintenance intervention on a named
carriageway, and throwing away everything that merely mentions a road.

Measured 2026-10-28 on the full export: 98,866 processes, of which 3,233 are FERMA or Federal
Ministry of Works and road-related. After the intervention filter below, fewer survive — and
that is the point.
"""

from __future__ import annotations

import re
from pathlib import Path

import pandas as pd

from roadsense.states import find_state
from roadsense.textmatch import extract_phrases

#: Text columns that may carry the project description, in order of usefulness.
TEXT_COLUMNS = (
    "planning_budget_project",
    "planning_budget_description",
    "planning_rationale",
    "tender_title",
    "tender_description",
)

#: Buyers that actually maintain federal roads.
ROAD_BUYER_PATTERN = re.compile(r"road maintenance|ministry of works", re.IGNORECASE)

#: Something in the text must suggest a carriageway, or it is not our problem.
ROAD_PATTERN = re.compile(
    r"\b(?:road|roads|highway|expressway|bypass|carriageway)\b", re.IGNORECASE
)

#: Interventions that indicate a road needed work. These are the events we want.
MAINTENANCE_PATTERN = re.compile(
    r"\b(maintenance|repair|repairs|rehabilitation|rehabilitate|reinstatement|"
    r"resurfac|overlay|patching|patch|reclamation|restoration)\b",
    re.IGNORECASE,
)

#: New-build and upgrade works. Excluded: a road being built is not a road failing.
CONSTRUCTION_PATTERN = re.compile(
    r"\b(construction|construct|reconstruction|reconstruct|dualisation|dualization|"
    r"dualling|widening|upgrade|upgrading|new\s+road|extension)\b",
    re.IGNORECASE,
)

#: Things that contain the word "road" but have nothing to do with pavement condition.
NOISE_PATTERN = re.compile(
    r"(access\s+road|road\s+show|street\s+light|streetlight|solar|car\s*park|carnival|"
    r"billboard|signage|street\s+naming|road\s+naming)",
    re.IGNORECASE,
)


def resolve_bundle(csv_dir: Path) -> Path:
    """Locate the directory holding ``main.csv`` inside an extracted OCDS bundle.

    The publisher's tarball nests its contents in a ``full/`` directory, and has changed
    layout before, so search shallowly rather than assuming a fixed path.
    """
    candidates = [csv_dir, csv_dir / "full", *sorted(p for p in csv_dir.glob("*") if p.is_dir())]
    for candidate in candidates:
        if (candidate / "main.csv").exists():
            return candidate
    raise FileNotFoundError(
        f"no main.csv found under {csv_dir}; got {[p.name for p in csv_dir.glob('*')][:10]}"
    )


def load_main(csv_dir: Path) -> pd.DataFrame:
    """Load ``main.csv`` from an extracted OCDS bundle, keeping only what we need."""
    path = resolve_bundle(csv_dir) / "main.csv"
    if not path.exists():
        raise FileNotFoundError(f"expected {path}; extract the OCDS bundle first")
    frame = pd.read_csv(path, low_memory=False, usecols=_existing_columns(path))
    return frame


def _existing_columns(path: Path) -> list[str]:
    """Read the header and pick the columns that are actually present."""
    header = pd.read_csv(path, nrows=0).columns
    wanted = [
        "ocid",
        "date",
        "buyer_name",
        "planning_budget_amount_amount",
        "tender_value_amount",
        *TEXT_COLUMNS,
    ]
    keep = [column for column in wanted if column in header]
    if "ocid" not in keep:
        raise ValueError(f"{path} has no 'ocid' column; is this the OCDS main.csv?")
    return keep


def build_text(frame: pd.DataFrame) -> pd.Series:
    """Concatenate the description columns into one searchable string."""
    present = [column for column in TEXT_COLUMNS if column in frame.columns]
    return (
        frame[present]
        .fillna("")
        .astype(str)
        .agg(" ".join, axis=1)
        .str.replace(r"\s+", " ", regex=True)
        .str.strip()
    )


def classify_intervention(text: str) -> str:
    """Label a description as maintenance, construction, access, noise, or other.

    Order matters: noise is checked first because "construction of access road" would
    otherwise be classified as construction works and kept in some future variant.
    """
    if NOISE_PATTERN.search(text):
        return "noise"
    if not ROAD_PATTERN.search(text):
        return "no_road"
    if CONSTRUCTION_PATTERN.search(text):
        return "construction"
    if MAINTENANCE_PATTERN.search(text):
        return "maintenance"
    return "other"


def _series(frame: pd.DataFrame, column: str, default: object = "") -> pd.Series:
    """Return a column if present, otherwise a default-filled series of the same length."""
    if column in frame.columns:
        return frame[column]
    return pd.Series([default] * len(frame), index=frame.index)


def extract_events(frame: pd.DataFrame) -> pd.DataFrame:
    """Filter the raw export down to maintenance events with a road phrase and a state."""
    text = build_text(frame)
    working = pd.DataFrame(
        {
            "ocid": frame["ocid"],
            "date": pd.to_datetime(_series(frame, "date", None), errors="coerce", utc=True),
            "buyer": _series(frame, "buyer_name").fillna(""),
            "text": text,
            "amount": pd.to_numeric(
                _series(frame, "planning_budget_amount_amount", None), errors="coerce"
            ),
            "tender_amount": pd.to_numeric(
                _series(frame, "tender_value_amount", None), errors="coerce"
            ),
        }
    )

    working = working[working["buyer"].str.contains(ROAD_BUYER_PATTERN, na=False)].copy()
    working["intervention"] = working["text"].map(classify_intervention)

    kept = working[working["intervention"] == "maintenance"].copy()
    kept["state"] = kept["text"].map(find_state)
    kept["road_phrase"] = kept["text"].map(_best_phrase)
    kept["year"] = kept["date"].dt.year
    return kept.reset_index(drop=True)


def _best_phrase(text: str) -> str | None:
    """Pick the longest extracted phrase; longer phrases carry more place tokens."""
    phrases = extract_phrases(text)
    if not phrases:
        return None
    return max(phrases, key=lambda phrase: len(phrase.split()))


def summarise_filter(frame: pd.DataFrame) -> dict[str, int]:
    """Counts at each filter stage, for the transparency table in the report."""
    text = build_text(frame)
    buyer_mask = frame.get("buyer_name", pd.Series("", index=frame.index)).fillna("")
    buyer_road = buyer_mask.str.contains(ROAD_BUYER_PATTERN, na=False)
    road_mention = text.str.contains(ROAD_PATTERN, na=False)
    classes = text.map(classify_intervention)
    return {
        "total_processes": int(len(frame)),
        "road_buyers": int(buyer_road.sum()),
        "buyers_and_road_mention": int((buyer_road & road_mention).sum()),
        "classified_maintenance": int((classes == "maintenance").sum()),
        "classified_construction": int((classes == "construction").sum()),
        "classified_noise": int((classes == "noise").sum()),
        "classified_other": int((classes == "other").sum()),
        "classified_no_road": int((classes == "no_road").sum()),
    }
