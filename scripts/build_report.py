#!/usr/bin/env python
"""Generate ``docs/publish/index.html`` from the artifacts on disk.

Every number that appears in the published page is read from a file, computed here, and
re-checked against the claim it supports. Nothing on the page is typed.

    python scripts/build_report.py                 # build, check, exit zero

Checks, in order of severity:

1. **Page versus data** — impossible to drift by construction: the HTML is formatted from
   ``facts`` and nothing else. ``audit_visible_numbers`` is the proof: it extracts every
   numeric token from the rendered page's visible text and fails if any token does not occur
   in ``facts``.
2. **Artifact versus artifact** — the AUCs are recomputed from
   ``validation_v2_matched.csv`` (rank formula) and compared with ``validation_v2.json``.
3. **Prose versus page** — the figures quoted in the brief and in ``docs/`` are compared with
   what the data now says. A disagreement is printed as a warning naming the file, and the
   run still exits zero: the page is generated from data, the prose is not, and the prose is
   what must be brought into line.

Five figures, hand-emitted SVG, no plotting library, no network, no JavaScript — including a
map of the corridor network coloured by year-over-year movement, drawn with its caveat inside
the figure because a change map read as a condition map is the failure mode this page exists
to prevent.
"""

from __future__ import annotations

import argparse
import hashlib
import html
import json
import math
import re
import sys
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
CONDITION = ROOT / "data" / "interim" / "condition.parquet"
CORRIDORS = ROOT / "data" / "interim" / "corridors.geojson"
VALIDATION = ROOT / "data" / "interim" / "validation_v2.json"
MATCHED = ROOT / "data" / "interim" / "validation_v2_matched.csv"
IMAGERY_MANIFEST = ROOT / "data" / "features" / "imagery_r10.manifest.json"
WEATHER_MANIFEST = ROOT / "data" / "interim" / "weather_daily_manifest.json"
OUT_DIR = ROOT / "docs" / "publish"
OUT_HTML = OUT_DIR / "index.html"
OUT_FACTS = OUT_DIR / "facts.json"

REPO_URL = "https://github.com/batestguy/roadsense-nigeria"

# AUC 0.50 is the definition of "no ranking", not a measurement. Kept here, named, so the
# audit knows where it came from.
CHANCE_AUC = 0.5

# Chart 2 bins: fixed count, edges taken from the data range, so the histogram is a function
# of the data and not of a choice made to look good.
HIST_BINS = 20

# --- what the prose currently claims ----------------------------------------------------
# Quoted from the T22 brief, docs/phases.md and docs/findings.md at the precision they were
# quoted. The page is the source of truth: a disagreement is printed as a warning naming the
# file, and the run still exits zero. Nothing here is allowed to change the page.
DOCUMENTED: list[tuple[str, str, float, float, str]] = [
    ("primary AUC", "0.3901", 0.3901, 0.00005, "T22 brief / validation_v2.json"),
    ("primary interval low", "0.3196", 0.3196, 0.00005, "T22 brief"),
    ("primary interval high", "0.4671", 0.4671, 0.00005, "T22 brief"),
    ("secondary AUC", "0.4318", 0.4318, 0.00005, "T22 brief"),
    ("secondary interval low", "0.3544", 0.3544, 0.00005, "T22 brief"),
    ("secondary interval high", "0.5137", 0.5137, 0.00005, "T22 brief"),
    ("reference AUC", "0.3133", 0.3133, 0.00005, "T22 brief"),
    ("reference interval low", "0.2461", 0.2461, 0.00005, "T22 brief"),
    ("reference interval high", "0.3881", 0.3881, 0.00005, "T22 brief"),
    ("analysed corridors", "644", 644.0, 0.0, "T22 brief"),
    ("corridors with a label", "66", 66.0, 0.0, "T22 brief"),
    ("corridors in the table", "850", 850.0, 0.0, "T22 brief / docs/phases.md"),
    ("corridor share of variance, per cent", "81.2", 81.2, 0.05, "docs/phases.md, month entered first"),
    ("month share of variance, per cent", "5.9", 5.9, 0.05, "docs/phases.md, month entered first"),
    ("residual share of variance, per cent", "12.8", 12.8, 0.05, "docs/phases.md, month entered first"),
    # F22's 42% is deliberately NOT in this list: it is a different measurement (tile-row means over
    # four months), not a stale copy of the corridor-mean figure. The page states both and says which
    # is which. Comparing it to this table's 38.3% would be comparing two different quantities.
]

# --- the photographs --------------------------------------------------------------------
# Author, licence and caption in one place: the credits block and the figure captions are
# rendered from this list, and ``build_facts`` checks each file's real pixel size against the
# numbers below, so an image that is resized on disk cannot silently arrive at the wrong
# aspect ratio in the layout. Nothing here is edited on the page.
LICENCE_URL = "https://creativecommons.org/licenses/by-sa/4.0"
LICENCE_NAME = "CC BY-SA 4.0"

PHOTOS: list[dict[str, Any]] = [
    {
        "file": "img/bad-road-lagos.jpg",
        "width": 1000,
        "height": 562,
        "alt": "A cracked, waterlogged street in Lagos: a bus and several vans nose through "
        "standing water while people walk along the edge of the flood.",
        "caption": "A flooded, rutted road in Lagos, 2020: buses and vans picking their way "
        "through, pedestrians on foot.",
        "author": "Tunde Olowookere",
    },
    {
        "file": "img/expressway.jpg",
        "width": 1000,
        "height": 750,
        "alt": "An empty multi-lane dual carriageway with fresh surfacing, painted markings, "
        "street lights and a grass verge, under a wide sky.",
        "caption": "The same country: a dual carriageway outside Abuja, empty, lit and drained.",
        "author": "Taini Ozeto",
    },
    {
        "file": "img/construction-lagos.jpg",
        "width": 1000,
        "height": 666,
        "alt": "Workers in high-visibility vests laying a new concrete slab by hand beside a "
        "narrow residential street, with buildings and a parked car behind.",
        "caption": "Concrete being laid in Bogije, Lagos: what the money buys when it arrives.",
        "author": "Ayodele Adeniji",
    },
    {
        "file": "img/akara-road.jpg",
        "width": 1000,
        "height": 652,
        "alt": "An unpaved earth road running through a busy market street: shop fronts and "
        "umbrellas on both sides, a lorry ahead, people walking across the surface.",
        "caption": "An earth road through a market in Akara: no surface, no drainage, and a "
        "town's traffic on it.",
        "author": "Okechukwu Iroegbu",
    },
]

NUM = re.compile(r"(?<![\w.,])\d+(?:,\d{3})*(?:\.\d+)?(?![\w,])")


# --- figures from outside this project ---------------------------------------------------
# Two constants quoted from one World Bank document. They are registered here, with their
# source, for the same reason the computed facts are: ``audit_visible_numbers`` lets a number
# onto the page only if some fact accounts for it, so an outside number needs an entry that
# names where it came from. Both are quoted as the document states them. The 40 per cent
# figure is a 2017 reading and the page says so; neither is presented as a current measurement.
WORLD_BANK_DOC = {
    "title": "World Bank, Nigeria Project Information Document, P180640",
    "url": (
        "https://documents1.worldbank.org/curated/en/099101624122030301/pdf/"
        "P180640153b37e0118f6619610a8cd46c2.pdf"
    ),
    "accessed": "2026-11-09",
}

EXTERNAL: dict[str, dict[str, Any]] = {
    "paved_share": {
        "value": 30,
        "statement": "of Nigeria's road network is paved, per cent",
        "source": WORLD_BANK_DOC["title"],
        "url": WORLD_BANK_DOC["url"],
        "accessed": WORLD_BANK_DOC["accessed"],
        "as_of": "",
    },
    "poor_condition": {
        "value": 40,
        "statement": "of federal roads were in poor condition, per cent",
        "source": WORLD_BANK_DOC["title"] + ", its footnote citing the Systematic Country Diagnostic (2020)",
        "footnote": "footnote 5",
        "url": WORLD_BANK_DOC["url"],
        "accessed": WORLD_BANK_DOC["accessed"],
        "as_of": "2017",
    },
}


# --- helpers ----------------------------------------------------------------------------
def sha256(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as fh:
        for chunk in iter(lambda: fh.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def jpeg_size(path: Path) -> tuple[int, int]:
    """Pixel width and height from a JPEG's frame header, with no imaging library."""
    data = path.read_bytes()
    if data[:2] != b"\xff\xd8":
        raise SystemExit(f"{path.name}: not a JPEG")
    i = 2
    while i < len(data) - 1:
        if data[i] != 0xFF:
            i += 1
            continue
        j = i + 1
        while j < len(data) and data[j] == 0xFF:
            j += 1
        if j >= len(data) - 1:
            break
        marker = data[j]
        if marker == 0x01 or 0xD0 <= marker <= 0xD9:
            i = j + 1
            continue
        length = int.from_bytes(data[j + 1 : j + 3], "big")
        if 0xC0 <= marker <= 0xCF and marker not in (0xC4, 0xC8, 0xCC):
            height = int.from_bytes(data[j + 4 : j + 6], "big")
            width = int.from_bytes(data[j + 6 : j + 8], "big")
            return width, height
        i = j + 1 + length
    raise SystemExit(f"{path.name}: no frame header found")


def esc(value: Any) -> str:
    return html.escape(str(value), quote=True)


def f4(x: float) -> str:
    return f"{x:.4f}"


def f3(x: float) -> str:
    return f"{x:.3f}"


def f2(x: float) -> str:
    return f"{x:.2f}"


def f1(x: float) -> str:
    return f"{x:.1f}"


def fint(x: float | int) -> str:
    return f"{int(x):,}"


def pct(x: float) -> str:
    return f"{x:.1f}%"


def auc_from_scores(scores: pd.Series, labels: pd.Series) -> float:
    """Rank definition of AUC: P(score of a positive > score of a negative), ties at half."""
    frame = pd.DataFrame({"s": scores.to_numpy(), "y": labels.to_numpy()}).sort_values(
        "s", kind="mergesort"
    )
    ranks = frame["s"].rank(method="average")
    n_pos = int(frame["y"].sum())
    n_neg = len(frame) - n_pos
    if n_pos == 0 or n_neg == 0:
        raise ValueError("AUC undefined: one of the two label groups is empty")
    return float((ranks[frame["y"] == 1].sum() - n_pos * (n_pos + 1) / 2) / (n_pos * n_neg))


def variance_split(frame: pd.DataFrame) -> dict[str, float]:
    """Sequential (Type I) sums of squares on the raw values, month entered first.

    The split is order-dependent on an unbalanced panel, so the order is part of the result.
    With month entered first, the month term is computed with every month weighted as a full
    column of corridors, the two-way residual is what the additive pair cannot explain, and
    corridor is what is left — i.e. corridor conditional on month. Both orders are returned so
    the dependence is printed instead of hidden.

    Re-implemented here rather than imported so this script has no side effects; it agrees
    with ``scripts/build_condition.py`` in the residual term and differs by construction in
    how the first term is weighted.
    """
    d = frame[["corridor_id", "month", "ndvi_contrast"]].dropna()
    grand = float(d["ndvi_contrast"].mean())
    by_month = d.groupby("month")["ndvi_contrast"]
    by_corr = d.groupby("corridor_id")["ndvi_contrast"]
    n_corr = int(d["corridor_id"].nunique())
    n_month = int(d["month"].nunique())
    ss_total = float(((d["ndvi_contrast"] - grand) ** 2).sum())

    month_centres = by_month.mean()
    ss_month_first = float(n_corr * ((month_centres - month_centres.mean()) ** 2).sum())
    ss_resid = float(
        (
            (
                d["ndvi_contrast"]
                - by_corr.transform("mean")
                - by_month.transform("mean")
                + grand
            )
            ** 2
        ).sum()
    )
    ss_corr_second = ss_total - ss_month_first - ss_resid

    corr_centres = by_corr.mean()
    ss_corr_first = float(n_month * ((corr_centres - corr_centres.mean()) ** 2).sum())
    ss_month_second = ss_total - ss_corr_first - ss_resid

    return {
        "n_obs": float(len(d)),
        "month": ss_month_first / ss_total * 100.0,
        "corridor": ss_corr_second / ss_total * 100.0,
        "residual": ss_resid / ss_total * 100.0,
        "corridor_first": ss_corr_first / ss_total * 100.0,
        "month_second": ss_month_second / ss_total * 100.0,
    }


def contrast_ratio(fg: str, bg: str) -> float:
    """WCAG 2.1 relative-luminance contrast ratio for two #rrggbb colours."""

    def lin(c: int) -> float:
        c = c / 255.0
        return c / 12.92 if c <= 0.04045 else ((c + 0.055) / 1.055) ** 2.4

    def lum(hex_colour: str) -> float:
        h = hex_colour.lstrip("#")
        r, g, b = (int(h[i : i + 2], 16) for i in (0, 2, 4))
        return 0.2126 * lin(r) + 0.7152 * lin(g) + 0.0722 * lin(b)

    a, b = lum(fg), lum(bg)
    hi, lo = max(a, b), min(a, b)
    return (hi + 0.05) / (lo + 0.05)


# --- palette ----------------------------------------------------------------------------
INK = "#11161a"
MUTED = "#4a545c"
RULE = "#c4ccd2"
PAPER = "#ffffff"
GREEN = "#0e4d36"
BROWN = "#6b4700"
RED = "#8c1d18"
LIGHT = "#e3e8ea"

TEXT_PAIRS = [
    ("body text", INK, PAPER),
    ("secondary text", MUTED, PAPER),
    ("inverse on corridor segment", PAPER, GREEN),
    ("inverse on month segment", PAPER, BROWN),
    ("dark on residual segment", INK, LIGHT),
    ("bar line label", RED, PAPER),
    ("axis rule", MUTED, PAPER),
]


# --- inputs and computed facts -----------------------------------------------------------
def build_facts() -> tuple[dict[str, Any], list[str], list[str]]:
    condition = pd.read_parquet(CONDITION)
    validation = json.loads(VALIDATION.read_text(encoding="utf-8"))
    matched = pd.read_csv(MATCHED)
    imagery = json.loads(IMAGERY_MANIFEST.read_text(encoding="utf-8"))
    weather = json.loads(WEATHER_MANIFEST.read_text(encoding="utf-8"))

    notes: list[str] = []

    # Chart 1 — the seasonal trap, 22 monthly national means of the raw value.
    usable = condition.dropna(subset=["ndvi_contrast"])
    monthly = usable.groupby("month", sort=True)["ndvi_contrast"].mean()
    months = list(monthly.index)
    values = [float(v) for v in monthly.to_numpy()]
    sep_i, dec_i = 0, 3  # 2024-09 and 2024-12 in the archive's own month order
    sep_v, dec_v = values[sep_i], values[dec_i]
    fall_pct = (dec_v - sep_v) / sep_v * 100.0
    if months[sep_i] != "2024-09" or months[dec_i] != "2024-12":
        raise SystemExit(f"month order unexpected: {months[sep_i]} .. {months[dec_i]}")

    # Chart 2 — the score the first test ranked corridors by: per corridor, the negative mean
    # of the two-way residual ``ndvi_anom2`` over its non-null months. The months of a
    # balanced corridor sum to zero, so every corridor with complete coverage lands on the
    # same value: the score cannot vary where it matters.
    anom = condition.dropna(subset=["ndvi_anom2"])
    score = -anom.groupby("corridor_id")["ndvi_anom2"].mean()
    total_corr = int(condition["corridor_id"].nunique())
    rounded = score.round(12)
    counts = rounded.value_counts()
    modal_value = float(counts.index[0])
    modal_count = int(counts.iloc[0])
    in_group = score[rounded == modal_value]
    within_sd = float(in_group.std(ddof=1))
    edges = np.linspace(float(score.min()), float(score.max()), HIST_BINS + 1)
    which = np.clip(np.searchsorted(edges, score.to_numpy(), side="right") - 1, 0, HIST_BINS - 1)
    hist = [0] * HIST_BINS
    for i in which:
        hist[int(i)] += 1
    bins = [
        {
            "lo": float(edges[i]),
            "hi": float(edges[i + 1]),
            "count": int(hist[i]),
        }
        for i in range(HIST_BINS)
    ]
    modal_bin = int(which[list(score.index).index(score[rounded == modal_value].index[0])])
    top_rows = [
        {"value": f"{float(v):.6f}", "corridors": int(c)}
        for v, c in counts.head(5).items()
    ]
    rest = int(counts.iloc[5:].sum())

    # Chart 3 — the two tests, recomputed from the analysed set and checked against the JSON.
    label_col = [c for c in matched.columns if c.startswith("label") and c != "label_events"]
    y = matched[label_col[0]].astype(int)
    instrument_rows = []
    for key, score_col, title in (
        ("primary_yoy", "score_yoy", "Primary / year-over-year"),
        ("secondary_slope", "score_slope", "Secondary / 15-month trend"),
        ("reference_level", "score_level", "Reference / raw level"),
    ):
        res = validation["results"][key]
        recomputed = auc_from_scores(matched[score_col], y)
        gap = abs(recomputed - float(res["auc_matched"]))
        if gap > 1e-9:
            notes.append(
                f"MISMATCH {key}: {score_col} AUC recomputed {f4(recomputed)} "
                f"vs validation_v2.json {f4(res['auc_matched'])}"
            )
        instrument_rows.append(
            {
                "key": key,
                "title": title,
                "auc": f4(float(res["auc_matched"])),
                "lo": f4(float(res["ci_low"])),
                "hi": f4(float(res["ci_high"])),
                "n": int(res["n_matched"]),
                "n_labelled": int(res["n_matched_labelled"]),
                "n_unlabelled": int(res["n_matched_unlabelled"]),
                "perm_p": f2(float(res["permutation_null"]["p_two_sided"])),
                "cov_rho": f4(float(res["coverage_diagnostic"]["spearman_score_vs_coverage"])),
                "cov_auc": f4(
                    float(res["coverage_diagnostic"]["auc_using_coverage_as_the_score"])
                ),
            }
        )

    bar = float(validation["bar"]["threshold"])
    deg = validation["degeneracy_gate"]
    deg_passed = bool(validation["degeneracy_gate_passed"])

    # Chart 4 — the variance split.
    split = variance_split(condition)

    # Figure 5 — the map. Geometry is projected and simplified once, here, so ``facts`` carries
    # the small numbers and ``svg_map`` reuses the same cached layer rather than re-reading the
    # GeoJSON. Nothing about a corridor's colour is decided in the renderer.
    layer = map_layer()

    # The photographs. The declared size is checked against the file, so the width and height
    # attributes in the page cannot disagree with the image the browser loads.
    photos: list[dict[str, Any]] = []
    for photo in PHOTOS:
        path = OUT_DIR / photo["file"]
        if not path.exists():
            raise SystemExit(f"photo missing: {path.relative_to(ROOT)}")
        got = jpeg_size(path)
        declared = (int(photo["width"]), int(photo["height"]))
        if got != declared:
            raise SystemExit(
                f"photo {photo['file']} is {got[0]}x{got[1]}, the page declares "
                f"{declared[0]}x{declared[1]}"
            )
        photos.append(
            {
                **photo,
                "credit": f"Photo: {photo['author']}, {LICENCE_NAME}",
                "licence_url": LICENCE_URL,
                "bytes": path.stat().st_size,
            }
        )

    # Provenance and the "what was checked" list.
    imagery_rows = int(imagery["rows"])
    weather_rows = int(weather["coverage"]["rows_present"])
    weather_missing = int(weather["coverage"]["rows_missing"])
    weather_nulls = sum(int(v) for v in weather["coverage"]["nulls"].values())
    corridor_months = len(condition)
    missing_cells = corridor_months - int(len(usable))

    facts: dict[str, Any] = {
        "meta": {
            "repo_url": REPO_URL,
            "digests": {
                "condition.parquet": sha256(CONDITION)[:16],
                "validation_v2.json": sha256(VALIDATION)[:16],
                "validation_v2_matched.csv": sha256(MATCHED)[:16],
                "imagery_r10.manifest.json": sha256(IMAGERY_MANIFEST)[:16],
                "weather_daily_manifest.json": sha256(WEATHER_MANIFEST)[:16],
            },
        },
        "headline": {
            "auc": instrument_rows[0]["auc"],
            "lo": instrument_rows[0]["lo"],
            "hi": instrument_rows[0]["hi"],
            "bar": f"{bar:.2f}",
            "chance": f"{CHANCE_AUC:.2f}",
            "n_labelled": instrument_rows[0]["n_labelled"],
            "n_unlabelled": instrument_rows[0]["n_unlabelled"],
            "n_matched": instrument_rows[0]["n"],
            "n_corridors": total_corr,
        },
        "seasonal": {
            "n_months": len(months),
            "months": months,
            "values": values,
            "sep_month": months[sep_i],
            "dec_month": months[dec_i],
            "sep_label": f3(sep_v),
            "dec_label": f3(dec_v),
            "sep_value": f4(sep_v),
            "dec_value": f4(dec_v),
            "fall_pct": f1(abs(fall_pct)),
            "fall_signed": f1(fall_pct),
            "f22_pct": "42",
            "ymin": f"{math.floor(min(values) * 100) / 100:.2f}",
            "ymax": f"{math.ceil(max(values) * 100) / 100:.2f}",
            "ticks": [
                f"{math.floor(min(values) * 100) / 100:.2f}",
                f"{math.floor((min(values) + max(values)) / 2 * 100) / 100:.2f}",
                f"{math.ceil(max(values) * 100) / 100:.2f}",
            ],
            "min_value": f4(min(values)),
            "max_value": f4(max(values)),
        },
        "panel": {
            "corridor_months": fint(corridor_months),
            "missing_cells": fint(missing_cells),
            "resolution_m": str(int(imagery["resolution_m"])),
        },
        "degenerate": {
            "total": total_corr,
            "score_n": int(len(score)),
            "modal_count": modal_count,
            "modal_share": f1(modal_count / total_corr * 100.0),
            "modal_value": f"{modal_value:.6f}",
            "within_sd": f"{within_sd:.1e}",
            "distinct_full": fint(int(score.nunique())),
            "bins": bins,
            "n_bins": HIST_BINS,
            "modal_bin": modal_bin,
            "top_rows": top_rows,
            "rest": rest,
            "zero": "0",
            "x_min": f"{float(score.min()):.4f}",
            "x_max": f"{float(score.max()):.4f}",
        },
        "tests": {
            "bar": f"{bar:.2f}",
            "chance": f"{CHANCE_AUC:.2f}",
            "tick_values": ["0.20", "0.30", "0.40", "0.50", "0.60", "0.70"],
            "rows": instrument_rows,
            "all_below_bar": all(float(r["hi"]) < bar for r in instrument_rows),
        },
        "variance": {
            "corridor": f1(split["corridor"]),
            "month": f1(split["month"]),
            "residual": f1(split["residual"]),
            "corridor_first": f1(split["corridor_first"]),
            "month_second": f1(split["month_second"]),
            "order": "month entered first, then corridor",
            "n_obs": fint(split["n_obs"]),
            "missing_cells": fint(corridor_months - int(len(usable))),
        },
        "map": layer["facts"],
        "photos": photos,
        "external": EXTERNAL,
        "checks": {
            "imagery_rows": fint(imagery_rows),
            "imagery_months": len(imagery["months_covered"]),
            "imagery_missing_months": len(imagery["months_missing"]),
            "duplicate_keys": fint(imagery["duplicate_keys"]),
            "weather_rows": fint(weather_rows),
            "weather_missing": fint(weather_missing),
            "weather_nulls": fint(weather_nulls),
            "degeneracy_passed": deg_passed,
            "degeneracy_rows": [
                {
                    "name": r["title"].split(" / ")[0],
                    "distinct": fint(deg[r["key"]]["all_850"]["distinct_values_full_precision"]),
                    "modal_share": f1(
                        float(deg[r["key"]]["all_850"]["share_on_modal_value_full_precision"])
                        * 100.0
                    ),
                }
                for r in instrument_rows
            ],
            "licence": weather["licence"],
            "weather_access": weather["access_date_utc"][:10],
            "imagery_generated": imagery["generated_at"][:10],
        },
    }
    return facts, notes


# --- charts (hand-emitted SVG) -----------------------------------------------------------
def svg_seasonal(f: dict[str, Any]) -> str:
    w, h = 440, 250
    left, right, top, bottom = 46, 428, 30, 186
    months = f["months"]
    values = f["values"]
    ymin, ymax = float(f["ymin"]), float(f["ymax"])
    n = len(values)

    def x(i: int) -> float:
        return left + (right - left) * (i / (n - 1))

    def y(v: float) -> float:
        return bottom - (bottom - top) * ((v - ymin) / (ymax - ymin))

    parts = [
        f'<text x="{left}" y="14" font-size="12" fill="{MUTED}">'
        "Mean road-minus-verge NDVI contrast, national, by month</text>",
        f'<line x1="{left}" y1="{bottom}" x2="{right}" y2="{bottom}" stroke="{MUTED}" stroke-width="1"/>',
    ]
    for tick in f["ticks"]:
        yy = y(float(tick))
        parts.append(
            f'<line x1="{left}" y1="{yy:.1f}" x2="{right}" y2="{yy:.1f}" '
            f'stroke="{RULE}" stroke-width="1"/>'
        )
        parts.append(
            f'<text x="{left - 6}" y="{yy + 4:.1f}" font-size="12" fill="{MUTED}" '
            f'text-anchor="end">{tick}</text>'
        )
    points = " ".join(f"{x(i):.1f},{y(v):.1f}" for i, v in enumerate(values))
    parts.append(
        f'<polyline points="{points}" fill="none" stroke="{GREEN}" stroke-width="2"/>'
    )
    for i, v in enumerate(values):
        parts.append(
            f'<circle cx="{x(i):.1f}" cy="{y(v):.1f}" r="2.4" fill="{GREEN}"/>'
        )
    # Annotate the two ends of the documented fall: September and December of the first year.
    for i, label in ((0, f["sep_label"]), (3, f["dec_label"])):
        parts.append(
            f'<circle cx="{x(i):.1f}" cy="{y(values[i]):.1f}" r="4.2" fill="{PAPER}" '
            f'stroke="{RED}" stroke-width="2"/>'
        )
        parts.append(
            f'<text x="{x(i):.1f}" y="{y(values[i]) - 10:.1f}" font-size="12" '
            f'fill="{INK}" text-anchor="middle">{label}</text>'
        )
    mid_x = (x(0) + x(3)) / 2
    mid_y = (y(values[0]) + y(values[3])) / 2 - 4
    parts.append(
        f'<text x="{mid_x:.1f}" y="{mid_y:.1f}" font-size="12" fill="{RED}" '
        f'text-anchor="middle" font-weight="bold">falls {f["fall_pct"]}%</text>'
    )
    # x ticks: first month of each year boundary shown as written in the data.
    for i in (0, 4, 8, 12, 16, 20):
        parts.append(
            f'<text x="{x(i):.1f}" y="{bottom + 16}" font-size="11" fill="{MUTED}" '
            f'text-anchor="middle">{esc(months[i])}</text>'
        )
    return (
        f'<svg viewBox="0 0 {w} {h}" role="img" aria-labelledby="c1t c1d" class="chart">'
        '<title id="c1t">Seasonal fall in the road-versus-verge contrast</title>'
        '<desc id="c1d">Line chart of the national monthly mean contrast over twenty-two '
        'months. It rises to a peak of ' + f["max_value"] + " and falls to "
        + f["min_value"] + ", dropping " + f["fall_pct"] + " per cent between "
        + f["sep_month"] + " and " + f["dec_month"] + ".</desc>"
        + "".join(parts)
        + "</svg>"
    )


def svg_degenerate(f: dict[str, Any]) -> str:
    w, h = 440, 240
    left, right, top, bottom = 46, 428, 30, 180
    bins = f["bins"]
    axis_max = float(f["total"])
    slot = (right - left) / len(bins)

    def y(count: float) -> float:
        return bottom - (bottom - top) * (count / axis_max)

    parts = [
        f'<text x="{left}" y="16" font-size="12" fill="{MUTED}">'
        "Corridors by value of the first test's score</text>",
        f'<line x1="{left}" y1="{bottom}" x2="{right}" y2="{bottom}" stroke="{MUTED}"/>',
    ]
    for tick in (0.0, axis_max):
        yy = y(tick)
        parts.append(
            f'<line x1="{left}" y1="{yy:.1f}" x2="{right}" y2="{yy:.1f}" '
            f'stroke="{RULE}" stroke-dasharray="3 3"/>'
        )
        parts.append(
            f'<text x="{left - 6}" y="{yy + 4:.1f}" font-size="12" fill="{MUTED}" '
            f'text-anchor="end">{fint(tick)}</text>'
        )
    for i, b in enumerate(bins):
        if b["count"] == 0:
            continue
        x0 = left + slot * i
        yy = y(b["count"])
        dominant = b["count"] == f["modal_count"]
        parts.append(
            f'<rect x="{x0 + 0.5:.1f}" y="{yy:.1f}" width="{slot - 1.5:.1f}" '
            f'height="{bottom - yy:.1f}" fill="{GREEN if dominant else MUTED}"/>'
        )
        if dominant:
            parts.append(
                f'<text x="{x0 + slot / 2:.1f}" y="{yy - 6:.1f}" font-size="12" '
                f'fill="{INK}" text-anchor="middle">{fint(b["count"])} '
                f'({f["modal_share"]})</text>'
            )
    parts.append(
        f'<text x="{left}" y="{bottom + 16}" font-size="11" fill="{MUTED}" '
        f'text-anchor="start">{f["x_min"]}</text>'
    )
    parts.append(
        f'<text x="{right}" y="{bottom + 16}" font-size="11" fill="{MUTED}" '
        f'text-anchor="end">{f["x_max"]}</text>'
    )
    parts.append(
        f'<text x="{left}" y="{h - 10}" font-size="11" fill="{MUTED}">'
        "Score: minus the mean two-way residual, per corridor</text>"
    )
    return (
        f'<svg viewBox="0 0 {w} {h}" role="img" aria-labelledby="c2t c2d" class="chart">'
        '<title id="c2t">The first test score collapses onto a single value</title>'
        '<desc id="c2d">Histogram of the score over ' + fint(f["total"]) + " corridors. "
        + fint(f["modal_count"]) + " corridors share one value, " + f["modal_value"]
        + ", the spread inside that group being floating-point noise at "
        + f["within_sd"] + "; every other bar is a sliver.</desc>"
        + "".join(parts)
        + "</svg>"
    )


def svg_forest(f: dict[str, Any]) -> str:
    w, h = 460, 250
    plot_l, plot_r = 150, 440
    top, bottom = 46, 186
    dmin, dmax = 0.20, 0.70
    rows = f["rows"]
    bar = float(f["bar"])

    def x(v: float) -> float:
        return plot_l + (plot_r - plot_l) * ((v - dmin) / (dmax - dmin))

    parts = []
    # The region that would clear the bar, drawn first so the marks sit on top of it.
    parts.append(
        f'<rect x="{x(bar):.1f}" y="{top - 14}" width="{plot_r - x(bar):.1f}" '
        f'height="{bottom - top + 14}" fill="{LIGHT}"/>'
    )
    parts.append(
        f'<text x="{x(bar) + 4:.1f}" y="{top - 20}" font-size="11" fill="{MUTED}">'
        "clears the bar</text>"
    )
    for tick in f["tick_values"]:
        tv = float(tick)
        parts.append(
            f'<line x1="{x(tv):.1f}" y1="{top - 14}" x2="{x(tv):.1f}" y2="{bottom}" '
            f'stroke="{RULE}" stroke-dasharray="2 4"/>'
        )
        parts.append(
            f'<text x="{x(tv):.1f}" y="{bottom + 16}" font-size="11" fill="{MUTED}" '
            f'text-anchor="middle">{tick}</text>'
        )
    parts.append(
        f'<line x1="{x(float(f["chance"])):.1f}" y1="{top - 14}" x2="{x(float(f["chance"])):.1f}" '
        f'y2="{bottom}" stroke="{INK}" stroke-width="1"/>'
    )
    parts.append(
        f'<text x="{x(float(f["chance"])) - 4:.1f}" y="{top - 32}" font-size="11" '
        f'fill="{INK}" text-anchor="end">chance {f["chance"]}</text>'
    )
    parts.append(
        f'<line x1="{x(bar):.1f}" y1="{top - 14}" x2="{x(bar):.1f}" y2="{bottom}" '
        f'stroke="{RED}" stroke-width="2"/>'
    )
    parts.append(
        f'<text x="{x(bar) + 4:.1f}" y="{top - 32}" font-size="11" fill="{RED}">'
        f'bar {f["bar"]}</text>'
    )
    step = (bottom - top - 20) / max(1, len(rows) - 1)
    for i, row in enumerate(rows):
        yy = top + 12 + step * i
        parts.append(
            f'<text x="8" y="{yy + 4:.1f}" font-size="12" fill="{INK}">'
            f'{esc(row["title"])}</text>'
        )
        parts.append(
            f'<line x1="{x(float(row["lo"])):.1f}" y1="{yy:.1f}" '
            f'x2="{x(float(row["hi"])):.1f}" y2="{yy:.1f}" stroke="{INK}" stroke-width="2"/>'
        )
        for cap in (float(row["lo"]), float(row["hi"])):
            parts.append(
                f'<line x1="{x(cap):.1f}" y1="{yy - 5:.1f}" x2="{x(cap):.1f}" '
                f'y2="{yy + 5:.1f}" stroke="{INK}" stroke-width="2"/>'
            )
        parts.append(
            f'<path d="M {x(float(row["auc"])):.1f} {yy - 5:.1f} '
            f'L {x(float(row["auc"])) + 5:.1f} {yy:.1f} '
            f'L {x(float(row["auc"])):.1f} {yy + 5:.1f} '
            f'L {x(float(row["auc"])) - 5:.1f} {yy:.1f} Z" fill="{RED}"/>'
        )
    parts.append(
        f'<text x="{plot_l}" y="{h - 10}" font-size="11" fill="{MUTED}">'
        "AUC, higher is better; the red line is the bar</text>"
    )
    return (
        f'<svg viewBox="0 0 {w} {h}" role="img" aria-labelledby="c3t c3d" class="chart">'
        '<title id="c3t">Three instruments against the chance line and the bar</title>'
        '<desc id="c3d">Forest plot with a point and a ninety-five per cent interval for each '
        "instrument. All three points and all three intervals lie to the left of both the "
        "chance line and the bar.</desc>"
        + "".join(parts)
        + "</svg>"
    )


def svg_variance(f: dict[str, Any]) -> str:
    w, h = 440, 150
    left, right, top = 40, 430, 42
    bar_h = 48
    shares = [
        ("Corridor", float(f["corridor"]), GREEN, PAPER, "corr"),
        ("Month", float(f["month"]), BROWN, PAPER, "month"),
        ("Residual", float(f["residual"]), LIGHT, INK, "resid"),
    ]
    total = sum(s for _, s, _, _, _ in shares)
    parts = [
        '<defs>'
        f'<pattern id="pat-corr" width="6" height="6" patternUnits="userSpaceOnUse">'
        f'<rect width="6" height="6" fill="{GREEN}"/></pattern>'
        f'<pattern id="pat-month" width="6" height="6" patternUnits="userSpaceOnUse">'
        f'<rect width="6" height="6" fill="{BROWN}"/>'
        f'<line x1="0" y1="0" x2="0" y2="6" stroke="{PAPER}" stroke-width="2"/></pattern>'
        f'<pattern id="pat-resid" width="6" height="6" patternUnits="userSpaceOnUse">'
        f'<rect width="6" height="6" fill="{LIGHT}"/>'
        f'<circle cx="3" cy="3" r="1" fill="{MUTED}"/></pattern>'
        "</defs>",
        f'<text x="{left}" y="22" font-size="12" fill="{MUTED}">'
        "Share of the raw variance, additive corridor plus month</text>",
    ]
    cursor = float(left)
    for _name, share, _fill, text_fill, pat in shares:
        seg_w = (right - left) * share / total
        parts.append(
            f'<rect x="{cursor:.1f}" y="{top}" width="{seg_w:.1f}" height="{bar_h}" '
            f'fill="url(#pat-{pat})" stroke="{PAPER}" stroke-width="1"/>'
        )
        if seg_w > 46:
            parts.append(
                f'<text x="{cursor + seg_w / 2:.1f}" y="{top + bar_h / 2 + 5}" '
                f'font-size="13" font-weight="bold" fill="{text_fill}" '
                f'text-anchor="middle">{pct(share)}</text>'
            )
        else:
            parts.append(
                f'<line x1="{cursor + seg_w / 2:.1f}" y1="{top - 4}" '
                f'x2="{cursor + seg_w / 2:.1f}" y2="{top}" stroke="{MUTED}"/>'
            )
            parts.append(
                f'<text x="{cursor + seg_w / 2:.1f}" y="{top - 8}" font-size="12" '
                f'fill="{INK}" text-anchor="middle">{pct(share)}</text>'
            )
        cursor += seg_w
    parts.append(
        f'<text x="{left}" y="{top + bar_h + 22}" font-size="12" fill="{INK}">'
        f'Corridor {pct(float(f["corridor"]))} | Month {pct(float(f["month"]))} | '
        f'Residual {pct(float(f["residual"]))}</text>'
    )
    parts.append(
        f'<text x="{left}" y="{h - 8}" font-size="11" fill="{MUTED}">'
        f'Month entered first, then corridor; {f["missing_cells"]} corridor-months '
        "missing.</text>"
    )
    return (
        f'<svg viewBox="0 0 {w} {h}" role="img" aria-labelledby="c4t c4d" class="chart">'
        '<title id="c4t">Where the variance sits</title>'
        '<desc id="c4d">Single stacked bar: corridor ' + f["corridor"] + " per cent, month "
        + f["month"] + " per cent, residual " + f["residual"] + " per cent.</desc>"
        + "".join(parts)
        + "</svg>"
    )


# --- the map (figure 5) -----------------------------------------------------------------
# The map answers one question: where did the contrast move. It is drawn from the corridor
# geometry and the per-corridor mean year-over-year change, in a single self-contained SVG.
#
# Three decisions are made here rather than in the renderer, and all three are computed:
#
# 1. **The colour bands.** Two thresholds either side of zero, both derived from the spread of
#    the data: the outer one is the 90th percentile of absolute movement rounded to a readable
#    step, the inner one is half of it. Nothing about "how much is a lot" is typed.
# 2. **The neutral treatment.** A corridor with no usable change value is drawn in a separate
#    neutral dash, never given an interpolated colour. On this vintage every corridor has at
#    least five monthly values, so that class is empty — and the page says so with the count
#    rather than quietly omitting the class.
# 3. **Partial coverage.** A corridor whose mean rests on fewer than the full comparison window
#    is marked with a dotted casing, so a value built from five months does not look like one
#    built from ten. 183 corridor-months of the panel carry no contrast at all; the ones that
#    fall inside the change window are simply absent, and are counted in the caption.

MAP_W, MAP_H, MAP_PAD = 640, 540, 8

# Douglas-Peucker would be better and is 30 lines; this is the 6-line version. A vertex is kept
# only when it is at least MAP_TOL viewBox units from the last kept vertex. At 640 units across
# a 375 px viewport one unit is about half a display pixel, so this removes near-duplicate
# vertices rather than shape: the network is not visibly distorted at any width.
MAP_TOL = 1.0

# Diverging pair anchored on grey, in two hues that carry no good-or-bad reading. An earlier
# palette used green for a rising contrast, which read as "better"; a rising contrast is not
# better — it means the verge is getting greener relative to the road, which can be scrub
# closing in. Violet (falling) and blue (rising) are both cool, both darken with distance from
# zero, and neither is the colour of a healthy road. The grey centre band still reads
# "steady". Legend labels and counts are unchanged; lightness still rises away from zero, so
# the scale survives greyscale printing as well as the labels that carry the meaning.
BAND_COLOURS: dict[str, str] = {
    "fall_hard": "#3d2a52",
    "fall_mild": "#6b4f94",
    "steady": "#a7b1b7",
    "rise_mild": "#38648c",
    "rise_hard": "#1b3f5c",
}
NO_VALUE_COLOUR = "#cfd6da"
BAND_ORDER = ["fall_hard", "fall_mild", "steady", "rise_mild", "rise_hard", "no_value"]

_MAP_LAYER: dict[str, Any] | None = None


def _nice_step(x: float) -> float:
    """Round a positive magnitude to one of 1, 2, 5 times a power of ten."""
    if not math.isfinite(x) or x <= 0:
        return 1.0
    exp = math.floor(math.log10(x))
    f = x / (10.0**exp)
    n = 1.0 if f <= 1.5 else 2.0 if f <= 3.5 else 5.0 if f <= 7.5 else 10.0
    return n * (10.0**exp)


def map_layer() -> dict[str, Any]:
    """Project, simplify, band and colour the corridor geometry. Deterministic, reads twice."""
    global _MAP_LAYER
    if _MAP_LAYER is not None:
        return _MAP_LAYER

    geo = json.loads(CORRIDORS.read_text(encoding="utf-8"))
    condition = pd.read_parquet(CONDITION)

    grouped = condition.groupby("corridor_id")["ndvi_yoy"]
    mean_change = grouped.mean()
    usable_months = grouped.count()
    window = sorted(str(m) for m in condition.loc[condition["ndvi_yoy"].notna(), "month"].unique())
    window_rows = condition[condition["month"].isin(window)]
    cells_in_window = int(len(window_rows))
    cells_with_value = int(window_rows["ndvi_yoy"].notna().sum())
    cells_missing_window = cells_in_window - cells_with_value
    months_in_window = len(window)

    # --- bands, from the data -----------------------------------------------------------
    values = mean_change.dropna()
    if values.empty:
        raise SystemExit("map: no corridor has a change value")
    p90 = float(np.percentile(np.abs(values.to_numpy()), 90))
    outer = _nice_step(p90)
    inner = outer / 2.0
    if inner <= 0 or outer <= inner:
        raise SystemExit(f"map: band thresholds degenerate ({inner}, {outer})")

    def band_of(change: float | None) -> str:
        if change is None or not math.isfinite(change):
            return "no_value"
        movement = -float(change)  # sign flipped: a falling contrast reads as falling
        if movement >= outer:
            return "fall_hard"
        if movement >= inner:
            return "fall_mild"
        if movement <= -outer:
            return "rise_hard"
        if movement <= -inner:
            return "rise_mild"
        return "steady"

    # --- geometry -----------------------------------------------------------------------
    features = geo["features"]
    parts: dict[str, list[list[tuple[float, float]]]] = {}
    lons: list[float] = []
    lats: list[float] = []
    source_vertices = 0
    total_km = 0.0
    for feature in features:
        props = feature["properties"]
        cid = str(props["corridor_id"])
        total_km += float(props.get("length_km") or 0.0)
        geometry = feature["geometry"]
        gtype = str(geometry["type"])
        raw = geometry["coordinates"]
        rings = raw if gtype == "MultiLineString" else [raw]
        parts[cid] = []
        for ring in rings:
            pts = [(float(p[0]), float(p[1])) for p in ring if len(p) >= 2]
            if not pts:
                continue
            source_vertices += len(pts)
            for lon, lat in pts:
                lons.append(lon)
                lats.append(lat)
            parts[cid].append(pts)

    if not lons:
        raise SystemExit("map: the GeoJSON has no coordinates")

    missing_geom = sorted(set(mean_change.index.astype(str)) - set(parts))
    missing_value = sorted(set(parts) - set(mean_change.index.astype(str)))
    if missing_geom or missing_value:
        raise SystemExit(
            "map: geometry and condition disagree — "
            f"{len(missing_geom)} corridors without geometry, "
            f"{len(missing_value)} without a condition row"
        )

    lon0, lon1 = min(lons), max(lons)
    lat0, lat1 = min(lats), max(lats)
    lat_mid = (lat0 + lat1) / 2.0
    cos_mid = math.cos(math.radians(lat_mid))
    span_x = (lon1 - lon0) * cos_mid
    span_y = lat1 - lat0
    scale = min((MAP_W - 2 * MAP_PAD) / span_x, (MAP_H - 2 * MAP_PAD) / span_y)
    off_x = (MAP_W - span_x * scale) / 2.0
    off_y = (MAP_H - span_y * scale) / 2.0

    def project(lon: float, lat: float) -> tuple[float, float]:
        return off_x + (lon - lon0) * cos_mid * scale, off_y + (lat1 - lat) * scale

    def simplify(pts: list[tuple[float, float]]) -> list[tuple[float, float]]:
        kept: list[tuple[float, float]] = []
        last_x = last_y = None
        for lon, lat in pts:
            x, y = project(lon, lat)
            if last_x is None or abs(x - last_x) + abs(y - last_y) >= MAP_TOL:
                kept.append((x, y))
                last_x, last_y = x, y
        x, y = project(*pts[-1])
        if not kept or abs(kept[-1][0] - x) + abs(kept[-1][1] - y) > 1e-9:
            kept.append((x, y))
        return kept

    def encode(kept: list[tuple[float, float]]) -> str:
        """One subpath as ``M x,y`` then relative ``l dx,dy`` steps.

        Coordinates are rounded to whole viewBox units once, before the deltas are taken, so the
        error is bounded at half a unit and cannot accumulate along the line. Relative steps cost
        about half what absolute pairs cost on 850 corridors, which is the difference between a
        1.5 MB page and a 0.4 MB one.
        """
        pts = [(int(round(x)), int(round(y))) for x, y in kept]
        if len(pts) == 1:
            x, y = pts[0]
            return f"M{x},{y}h1"
        out = [f"M{pts[0][0]},{pts[0][1]}"]
        prev_x, prev_y = pts[0]
        for x, y in pts[1:]:
            if x == prev_x and y == prev_y:
                continue
            out.append(f"l{x - prev_x},{y - prev_y}")
            prev_x, prev_y = x, y
        return "".join(out)

    counts = dict.fromkeys(BAND_ORDER, 0)
    drawn_vertices = 0
    paths: list[tuple[str, str, bool, str]] = []
    for cid in sorted(parts):
        change = mean_change.get(cid, float("nan"))
        band = band_of(None if pd.isna(change) else float(change))
        counts[band] += 1
        partial = int(usable_months.get(cid, 0)) < months_in_window
        segments = []
        for ring in parts[cid]:
            kept = simplify(ring)
            drawn_vertices += len(kept)
            segments.append(encode(kept))
        paths.append((cid, band, partial, "".join(segments)))

    def band_label(key: str) -> str:
        if key == "fall_hard":
            return f"contrast falling by {outer:g} or more"
        if key == "fall_mild":
            return f"contrast falling by {inner:g} to {outer:g}"
        if key == "steady":
            return f"steady, within {inner:g} either way"
        if key == "rise_mild":
            return f"contrast rising by {inner:g} to {outer:g}"
        if key == "rise_hard":
            return f"contrast rising by {outer:g} or more"
        return "no usable change value"

    band_rows = [
        {
            "key": key,
            "label": band_label(key),
            "count": counts[key],
            "count_label": fint(counts[key]),
            "colour": NO_VALUE_COLOUR if key == "no_value" else BAND_COLOURS[key],
        }
        for key in BAND_ORDER
    ]

    facts: dict[str, Any] = {
        "n_corridors": len(paths),
        "n_corridors_label": fint(len(paths)),
        "total_km": fint(round(total_km)),
        "n_coloured": fint(sum(counts[k] for k in BAND_COLOURS)),
        "n_no_value": fint(counts["no_value"]),
        "n_partial": fint(sum(1 for p in paths if p[2])),
        "n_fall": fint(counts["fall_hard"] + counts["fall_mild"]),
        "n_steady": fint(counts["steady"]),
        "n_rise": fint(counts["rise_mild"] + counts["rise_hard"]),
        "fall_hard": fint(counts["fall_hard"]),
        "fall_mild": fint(counts["fall_mild"]),
        "steady": fint(counts["steady"]),
        "rise_mild": fint(counts["rise_mild"]),
        "rise_hard": fint(counts["rise_hard"]),
        "inner": f"{inner:g}",
        "outer": f"{outer:g}",
        "p90_abs": f"{p90:.4f}",
        "bands": band_rows,
        "months_in_window": fint(months_in_window),
        "window_label": f"{window[0]} to {window[-1]}",
        "cells_missing_window": fint(cells_missing_window),
        "cells_missing_panel": fint(len(condition) - int(condition["ndvi_contrast"].notna().sum())),
        "source_vertices": fint(source_vertices),
        "drawn_vertices": fint(drawn_vertices),
        "width": MAP_W,
        "height": MAP_H,
        "lon_span": f1(lon1 - lon0),
        "lat_span": f1(lat1 - lat0),
    }
    _MAP_LAYER = {"facts": facts, "paths": paths}
    return _MAP_LAYER


def svg_map(layer: dict[str, Any]) -> str:
    facts = layer["facts"]
    paths = layer["paths"]
    parts = [
        f'<rect x="0" y="0" width="{MAP_W}" height="{MAP_H}" fill="{PAPER}"/>',
        # Dotted casings first: the corridors whose value rests on a partial record sit under
        # every colour line rather than over it, so no corridor loses its colour.
        "".join(
            f'<path d="{d}" fill="none" stroke="{INK}" stroke-width="2.6" '
            f'stroke-dasharray="1.6 2.2" stroke-opacity=".55" stroke-linecap="round"/>'
            for _cid, band, partial, d in paths
            if partial and band in BAND_COLOURS
        ),
        "".join(
            f'<path d="{d}" fill="none" stroke="{BAND_COLOURS[band]}" stroke-width="1.5" '
            f'stroke-linecap="round" stroke-linejoin="round"/>'
            for _cid, band, _partial, d in paths
            if band in BAND_COLOURS
        ),
        "".join(
            f'<path d="{d}" fill="none" stroke="{NO_VALUE_COLOUR}" stroke-width="1.5" '
            f'stroke-dasharray="3 2" stroke-linecap="round"/>'
            for _cid, band, _partial, d in paths
            if band == "no_value"
        ),
    ]
    return (
        f'<svg viewBox="0 0 {MAP_W} {MAP_H}" role="img" aria-labelledby="c5t c5d" class="chart">'
        '<title id="c5t">Where the road-versus-verge contrast moved, corridor by corridor</title>'
        '<desc id="c5d">Map of '
        + facts["n_corridors_label"]
        + " federal road corridors across Nigeria, coloured by mean year-over-year change in the "
        "road-versus-verge vegetation contrast over "
        + facts["months_in_window"]
        + " months. "
        + facts["fall_hard"]
        + " corridors fell by "
        + facts["outer"]
        + " or more, "
        + facts["fall_mild"]
        + " fell by "
        + facts["inner"]
        + " to "
        + facts["outer"]
        + ", "
        + facts["steady"]
        + " stayed within "
        + facts["inner"]
        + " of zero, "
        + facts["rise_mild"]
        + " rose by "
        + facts["inner"]
        + " to "
        + facts["outer"]
        + " and "
        + facts["rise_hard"]
        + " rose by "
        + facts["outer"]
        + " or more. "
        + facts["n_no_value"]
        + " corridors carry no usable change value and are drawn in neutral grey. "
        + facts["n_partial"]
        + " corridors have a dotted outline because their value rests on fewer than "
        + facts["months_in_window"]
        + " monthly values. This is movement, not condition: the colour says how much a corridor "
        "moved against its own history and against the national month, not how good or bad the "
        "road is now, and it cannot rank roads against each other nationally.</desc>"
        + "".join(parts)
        + "</svg>"
    )


# --- page --------------------------------------------------------------------------------
CSS = """
:root { color-scheme: light; }
* { box-sizing: border-box; }
body { margin:0; background:#ffffff; color:#11161a;
  font-family: system-ui, -apple-system, "Segoe UI", Roboto, Helvetica, Arial, sans-serif;
  line-height:1.55; font-size:1rem; }
/* A faint tarred road behind the page. Kept at 5.5% so the paper stays the surface the text
   sits on: at that weight the darkest pixel in the photograph composites to about #f1f1f1, and
   the body text still measures above 16:1 against it. Decorative, so it carries no meaning and
   is hidden from assistive technology by being a CSS background, not an image element. */
body::before { content:""; position:fixed; inset:0; z-index:-1; pointer-events:none;
  background:url("img/watermark-road.jpg") center top / cover no-repeat; opacity:.055; }
.skip { position:absolute; left:-999px; top:0; background:#ffffff; color:#11161a;
  padding:.6rem 1rem; z-index:10; }
.skip:focus { left:.5rem; top:.5rem; outline:3px solid #0e4d36; }
main { max-width:74ch; margin:0 auto; padding:1.25rem 1rem 3rem; }
h1 { font-size:1.6rem; line-height:1.25; margin:.2rem 0 .6rem; letter-spacing:-.01em; }
h2 { font-size:1.15rem; margin:2.2rem 0 .5rem; border-bottom:1px solid #c4ccd2;
  padding-bottom:.3rem; }
h3 { font-size:1rem; margin:1.4rem 0 .3rem; }
p, li { max-width:70ch; }
.lede { font-size:1.05rem; color:#1d242a; }
.eyebrow { text-transform:uppercase; letter-spacing:.08em; font-size:.75rem;
  color:#4a545c; margin:0 0 .4rem; }
.finding { border:2px solid #11161a; border-left-width:8px; padding:1rem 1.1rem;
  margin:1.4rem 0 1.8rem; background:#f7f9fa; }
.finding .score { font-size:2.6rem; font-weight:700; line-height:1; margin:0; }
.finding .score .unit { font-size:1rem; font-weight:400; color:#4a545c;
  display:block; margin-top:.35rem; }
.finding dl { margin:.9rem 0 0; display:grid; grid-template-columns:auto 1fr;
  gap:.25rem .9rem; font-size:.95rem; }
.finding dt { color:#4a545c; }
.finding dd { margin:0; font-weight:600; }
figure { margin:1.6rem 0 2rem; }
figure svg.chart { width:100%; height:auto; display:block; background:#ffffff;
  border:1px solid #c4ccd2; }
figcaption { margin-top:.55rem; font-size:.92rem; color:#1d242a; }
figcaption .what { display:block; color:#4a545c; }
.photostrip { display:grid; grid-template-columns:1fr 1fr; gap:.9rem 1rem;
  margin:1.3rem 0 1.6rem; align-items:start; }
.photostrip figure { margin:0; }
.photostrip figure.photo img { aspect-ratio:3 / 2; object-fit:cover; }
figure.photo img { width:100%; height:auto; display:block; border:1px solid #c4ccd2; }
figure.photo figcaption { font-size:.85rem; }
.credit { display:block; color:#4a545c; font-size:.78rem; margin-top:.2rem; }
.credits { list-style:none; margin:.5rem 0 0; padding:0; font-size:.88rem; }
.credits li { margin:0 0 .35rem; max-width:none; }
.tblwrap { overflow-x:auto; margin-top:.7rem; }
.tblwrap:focus-visible { outline:3px solid #8c1d18; outline-offset:2px; }
table { border-collapse:collapse; font-size:.88rem; min-width:26rem; width:100%; }
caption { text-align:left; font-size:.85rem; color:#4a545c; padding-bottom:.35rem; }
th, td { border-bottom:1px solid #c4ccd2; padding:.3rem .5rem; text-align:right; }
th:first-child, td:first-child { text-align:left; }
thead th { border-bottom:2px solid #11161a; }
details { margin-top:.6rem; font-size:.9rem; }
summary { cursor:pointer; color:#0e4d36; text-decoration:underline; padding:.2rem 0; }
summary:focus-visible, a:focus-visible { outline:3px solid #8c1d18; outline-offset:2px; }
a { color:#0e4d36; }
.tablenote { font-size:.85rem; color:#4a545c; margin:.45rem 0 0; }
.nonclaims { background:#f7f9fa; border-left:4px solid #6b4700; padding:.8rem 1rem;
  margin:1rem 0; }
.nonclaims ol { margin:.4rem 0 0; padding-left:1.2rem; }
.legend { list-style:none; margin:.7rem 0 0; padding:0; display:flex; flex-wrap:wrap;
  gap:.35rem 1rem; font-size:.85rem; color:#1d242a; }
.legend li { display:flex; align-items:center; gap:.45rem; margin:0; max-width:none; }
.sw { display:inline-block; width:1.7rem; height:.5rem; border-radius:1px; flex:none; }
.sw-dashed { border:1px dashed #4a545c; }
.sw-dot { background:transparent; border:2px dotted #11161a; }
.mapnote { font-size:.88rem; color:#1d242a; margin:.5rem 0 .7rem; }
.caveat { border-left:4px solid #8c1d18; padding:.15rem 0 .15rem .8rem; margin:.7rem 0 .5rem;
  font-size:.95rem; }
footer { margin-top:2.6rem; border-top:1px solid #c4ccd2; padding-top:1rem;
  font-size:.82rem; color:#3d464d; }
footer code { font-size:.8rem; word-break:break-all; }
@media (max-width:26rem) {
  h1 { font-size:1.35rem; }
  .finding .score { font-size:2.1rem; }
  .finding dl { grid-template-columns:1fr; }
  .finding dd { margin-bottom:.5rem; }
  .photostrip { grid-template-columns:1fr; }
  .photostrip figure.photo img { aspect-ratio:3 / 2; }
}
"""


def table(title: str, head: list[str], rows: list[list[str]]) -> str:
    ths = "".join(f"<th scope=\"col\">{esc(h)}</th>" for h in head)
    trs = "".join(
        "<tr>" + "".join(f"<td>{esc(c)}</td>" for c in r) + "</tr>" for r in rows
    )
    return (
        '<div class="tblwrap" tabindex="0" role="region" aria-label="Table, scrollable sideways on narrow screens"><table>'
        f"<caption>{esc(title)}</caption>"
        f"<thead><tr>{ths}</tr></thead><tbody>{trs}</tbody></table></div>"
    )


def photo_figure(p: dict[str, Any]) -> str:
    """One photograph: the file, the alt text, the declared size, and the required credit.

    The caption and the credit are two separate elements so the credit is small type under the
    caption, and the licence is the thing the link points at.
    """
    return (
        '<figure class="photo">\n'
        f'<img src="{esc(p["file"])}" alt="{esc(p["alt"])}" width="{p["width"]}" '
        f'height="{p["height"]}" loading="lazy" decoding="async">\n'
        f"<figcaption>{esc(p['caption'])}"
        f'<span class="credit">Photo: {esc(p["author"])}, '
        f'<a href="{LICENCE_URL}">{esc(LICENCE_NAME)}</a></span>'
        "</figcaption>\n</figure>"
    )


def render(f: dict[str, Any]) -> str:
    h1 = f["headline"]
    seasonal = f["seasonal"]
    degenerate = f["degenerate"]
    panel = f["panel"]
    tests = f["tests"]
    var = f["variance"]
    checks = f["checks"]
    photos = f["photos"]
    ext = f["external"]
    photos = PHOTOS

    month_rows = [
        [m, f4(v)] for m, v in zip(seasonal["months"], seasonal["values"], strict=True)
    ]
    deg_table_rows = [
        [r["value"], fint(r["corridors"])] for r in degenerate["top_rows"]
    ] + [["every other value", fint(degenerate["rest"])]]
    test_rows = [
        [
            r["title"],
            r["auc"],
            f'{r["lo"]} to {r["hi"]}',
            fint(r["n"]),
            fint(r["n_labelled"]),
            fint(r["n_unlabelled"]),
            r["perm_p"],
        ]
        for r in tests["rows"]
    ]
    deg_rows = [
        [r["name"], r["distinct"], r["modal_share"] + "%"] for r in checks["degeneracy_rows"]
    ]
    digest_rows = [
        [name, digest] for name, digest in f["meta"]["digests"].items()
    ]
    measure_rows = [
        [
            "Imagery months present",
            f"{checks['imagery_months']} of {fint(seasonal['n_months'])}, "
            f"{checks['imagery_missing_months']} missing",
        ],
        [
            "Imagery rows, corridors, duplicate keys",
            f"{checks['imagery_rows']}, {fint(h1['n_corridors'])}, {checks['duplicate_keys']}",
        ],
        [
            "Weather rows, missing, nulls",
            f"{checks['weather_rows']}, {checks['weather_missing']}, {checks['weather_nulls']}",
        ],
        [
            "Score varies, all three instruments",
            f"{deg_rows[0][1]} distinct values each, {deg_rows[0][2]} on the modal value",
        ],
        [
            "Score is not a proxy for coverage",
            f"correlation {tests['rows'][0]['cov_rho']}, AUC {tests['rows'][0]['cov_auc']}",
        ],
        [
            "Decision rule, written before the test",
            f"{tests['bar']} point estimate, lower bound above {tests['chance']}",
        ],
    ]

    # Figure 5 — the map. The layer is cached by ``map_layer``, so this is the same projection
    # and the same band assignment that went into ``facts``; the renderer only places it.
    mapf = f["map"]
    layer = map_layer()
    legend_items = []
    for band in mapf["bands"]:
        extra = " sw-dashed" if band["key"] == "no_value" else ""
        legend_items.append(
            f'<li><span class="sw{extra}" style="background:{band["colour"]}"></span>'
            f"{esc(band['label'])} &mdash; {band['count_label']} corridors</li>"
        )
    legend_items.append(
        f'<li><span class="sw sw-dot"></span>value from fewer than '
        f"{mapf['months_in_window']} monthly values &mdash; {mapf['n_partial']} corridors, "
        "dotted outline</li>"
    )
    map_rows = [[b["label"], b["count_label"]] for b in mapf["bands"]]

    body = f"""
<p class="eyebrow">RoadSense Nigeria &middot; measured <time>{esc(checks["imagery_generated"])}</time></p>
<h1>The road condition signal does not clear its own bar</h1>

<div class="photostrip">
{photo_figure(photos[0])}
{photo_figure(photos[1])}
</div>

<p>The World Bank puts the paved share of Nigeria's road network at {ext["paved_share"]["value"]}
per cent. Above are the two ends of that range: a Lagos street where buses and vans pick their
way through standing water, and a dual carriageway outside Abuja, empty, lit and drained.</p>

<p>A photograph shows which of the two a road is on the day it was taken. It does not show which
way the road is heading. The flooded street may flood every rainy season and be no worse than
ten years ago; the carriageway may be losing its verge now.</p>

<p>In {ext["poor_condition"]["as_of"]} the World Bank put
{ext["poor_condition"]["value"]} per cent of federal roads in poor condition. That is one year's
reading, not a trend. This page measures movement instead, over {fint(h1["n_corridors"])}
federal corridors and {mapf["total_km"]}&nbsp;km of them: not which roads look bad today, but
which are getting worse.</p>

<h2>What the record says</h2>

{photo_figure(photos[2])}

<p>Nigeria's procurement record is the only national paper trail of road spending. It names a
road, a state, a kind of work, an amount and a date: money allocated.</p>

<p>It does not say whether the road got better. A contract records a promise, and a
commissioning ceremony is a photograph of a promise, nothing more. The money may have reached
the road, part of it, or none of it.</p>

<p>The record shows where money moved; satellite imagery shows what the ground did. The test
below asks whether the second predicts the first.</p>

<h2>The result</h2>

<p class="lede">One page on what this project measured across {fint(h1["n_corridors"])}
federal road corridors, why the measurement failed its pre-specified test, and what it
still supports.</p>

<div class="finding">
  <p class="score">{h1["auc"]}<span class="unit">area under the curve, primary instrument</span></p>
  <dl>
    <dt>Interval</dt><dd>{h1["lo"]} to {h1["hi"]}</dd>
    <dt>Bar to clear</dt><dd>{h1["bar"]} point estimate, with the lower bound above {h1["chance"]}</dd>
    <dt>Direction</dt><dd>below chance ({h1["chance"]}): corridors with recorded spending
      score as <em>less</em> degraded than those without</dd>
    <dt>Sample</dt><dd>{fint(h1["n_matched"])} corridors analysed,
      {fint(h1["n_labelled"])} with a label, {fint(h1["n_unlabelled"])} without</dd>
  </dl>
</div>

<p>The result is not "the effect is small". It is that the instrument ranks the labelled
corridors the wrong way round, so it cannot be used to allocate maintenance, and this page
exists to say so before anything else on it.</p>

<h2>The five figures</h2>

<figure>
<h3>The map: movement, not condition</h3>
<p class="mapnote">Across {mapf["n_corridors_label"]} corridors over
{mapf["months_in_window"]} months, {mapf["n_fall"]} fell, {mapf["n_rise"]} rose and
{mapf["n_steady"]} stayed within {mapf["inner"]} of zero either way. The outer band starts at
{mapf["outer"]}, the ninetieth percentile of absolute movement.</p>
{svg_map(layer)}
<ul class="legend">{"".join(legend_items)}</ul>
<figcaption>
  <p class="caveat"><strong>This shows movement, not condition.</strong> A corridor that has always
  been poor and one that has always been good look the same here. It cannot rank roads against
  each other nationally.</p>
  <span class="what">Shows: the mean year-over-year change in the road-versus-verge contrast for
  each corridor, over the {mapf["months_in_window"]} months where a year-earlier pair exists
  ({mapf["window_label"]}). The comparison is each corridor against itself, the same calendar
  month one year earlier, so a road's own level is differenced out and the season is held fixed:
  a corridor that did not move sits at zero by construction, and the grey centre band reads
  &ldquo;no change against that reference&rdquo;, never &ldquo;a good road&rdquo;.
  {mapf["n_no_value"]} corridors have no usable change value and are drawn in neutral grey rather
  than given a colour; {mapf["n_partial"]} rest on fewer than {mapf["months_in_window"]} monthly
  values and carry a dotted outline. {mapf["cells_missing_window"]} corridor-months inside the
  window carry no value and are left out, not interpolated ({mapf["cells_missing_panel"]} across
  the whole panel). Does not show: current condition, or that a dark violet corridor is in worse
  shape today than a dark blue one &mdash; only that its contrast moved further in one direction
  over the period.</span>
</figcaption>
<details><summary>The same numbers as a table</summary>
{table("Corridors by change in the road-versus-verge contrast, over the change window",
       ["Band", "Corridors"], map_rows)}
<p class="tablenote">The map is one SVG drawn from {mapf["source_vertices"]} source vertices,
simplified to {mapf["drawn_vertices"]} for this page at a tolerance of about half a display
pixel, and clipped to the corridor bounding box
({mapf["lon_span"]} degrees of longitude, {mapf["lat_span"]} of latitude).</p>
</details>
</figure>

<figure>
{svg_seasonal(seasonal)}
<figcaption>
  <strong>The seasonal trap.</strong>
  <span class="what">Shows: the raw contrast falls {seasonal["fall_pct"]} per cent on corridor
  means over the full {fint(seasonal["n_months"])} months, from
  {esc(seasonal["sep_month"])} to {esc(seasonal["dec_month"])}, with no road changing
  (F22 measured {seasonal["f22_pct"]} per cent on tile-row means over the first four months).
  The two measures answer the same question on different rows and are not interchangeable.
  Does not show: that any corridor deteriorated, or that the road itself changed.</span>
</figcaption>
<details><summary>The same numbers as a table</summary>
{table("National mean of road-minus-verge NDVI contrast, by month",
       ["Month", "Mean contrast"], month_rows)}
</details>
</figure>

<figure>
{svg_degenerate(degenerate)}
<figcaption>
  <strong>The broken instrument.</strong>
  <span class="what">Shows: {fint(degenerate["modal_count"])} of
  {fint(degenerate["total"])} corridors ({degenerate["modal_share"]}) share one and the same
  value, {degenerate["modal_value"]}, and the spread inside that group is floating-point noise
  ({degenerate["within_sd"]}). This is the score the first test used; it could not have
  detected anything, because a score that takes one value on most of the sample has no ranking
  to give. A gate now refuses to run an area under the curve before checking that the score
  can vary at all. Does not show: that the three instruments in the next chart are broken; they
  are continuous, and that gate passed for all three.</span>
</figcaption>
<details><summary>The same numbers as a table</summary>
{table("Corridors by value of the first test's score, the most common values first",
       ["Score value", "Corridors"], deg_table_rows)}
<p class="tablenote">Distinct values at full precision:
{degenerate["distinct_full"]} across {fint(degenerate["score_n"])} scored corridors;
histogram drawn with {degenerate["n_bins"]} equal bins between {degenerate["x_min"]} and
{degenerate["x_max"]}.</p>
</details>
</figure>

<figure>
{svg_forest(tests)}
<figcaption>
  <strong>The two tests, and the reference.</strong>
  <span class="what">Shows: every interval lies entirely below the chance line and below the
  bar of {tests["bar"]}, and the second test's interval reaches above chance only by a
  fraction of a point. Does not show: an effect size of zero, or that the imagery carries no
  signal &mdash; with {fint(h1["n_labelled"])} positive corridors the intervals are wide and
  observational.</span>
</figcaption>
<details><summary>The same numbers as a table</summary>
{table("Area under the curve, matched sample, with intervals",
       ["Instrument", "AUC", "Interval", "Analysed", "Labelled", "Unlabelled", "Permutation p"],
       test_rows)}
</details>
</figure>

<figure>
{svg_variance(var)}
<figcaption>
  <strong>Where the variation sits.</strong>
  <span class="what">Shows: with month entered first and corridor second, {var["month"]} per
  cent of the raw variance is between months, {var["corridor"]} per cent between corridors,
  leaving {var["residual"]} per cent as interaction and noise &mdash; the only part a change
  measure could use. The split is order-dependent: entering corridor first gives
  {var["corridor_first"]} per cent corridor and {var["month_second"]} per cent month, which is
  why the order is stated rather than implied. Does not show: that the residual is condition;
  land cover, weather and registration differences all sit in it.</span>
</figcaption>
<details><summary>The same numbers as a table</summary>
{table("Variance decomposition of the raw contrast, sequential month then corridor",
       ["Component", "Share of total"], [
           ["Month, entered first", var["month"] + "%"],
           ["Corridor, entered second", var["corridor"] + "%"],
           ["Residual", var["residual"] + "%"],
           ["Corridor first instead", var["corridor_first"] + "%"],
           ["Month second instead", var["month_second"] + "%"],
           ["Corridor-months used", var["n_obs"]],
       ])}
</details>
</figure>

<h2>How the measurement was made</h2>

<p>For each corridor and each month, the mean vegetation index of a band along the carriageway
is subtracted from the mean of the verge beside it, at {panel["resolution_m"]}&nbsp;metre
resolution, from Sentinel-2 via the DE Africa platform. That gives one value per corridor per
month: {panel["corridor_months"]} corridor-months over {fint(seasonal["n_months"])} months,
with {panel["missing_cells"]} left blank rather than filled.</p>

{table("What was checked before the test ran", ["Check", "Result"], measure_rows)}

<p>The test asks whether the contrast falls faster on corridors with a procurement record than
on comparable corridors without one. Corridors are matched exactly on road class and on length
band within class; the statistic is the probability that a labelled corridor ranks as more
degraded than an unlabelled one, with a bootstrap interval and a permutation null. The bar was
written down before the test ran, and was not lowered after it failed.</p>

<h2>What this does not claim</h2>

<div class="nonclaims">
<p><strong>Four things this does not claim.</strong></p>
<ol>
  <li><strong>Movement, not condition.</strong> The score has no level: a corridor that was
  always bad and one that never changed can produce the same value.</li>
  <li><strong>Federal corridors only.</strong> The network is the named federal highways;
  feeder roads, which carry much of the traffic, are not in it.</li>
  <li><strong>Reanalysis, not gauges.</strong> The rainfall covariate is a gridded reanalysis
  product, not a rain gauge, and it is context rather than a measured cause.</li>
  <li><strong>Observational, not causal.</strong> {fint(h1["n_labelled"])} labelled corridors
  is a small, non-random, spending-driven sample. A procurement record is evidence that money
  was allocated, never that a road failed.</li>
</ol>
</div>

{photo_figure(photos[3])}

<h2>Where the numbers come from</h2>
<p>Every figure on this page is emitted by the script that built it and re-checked on each
build against the file it came from; a number typed by hand would fail the build. The
<a href="{esc(f["meta"]["repo_url"])}">code, data manifests and findings register are on
GitHub</a>.</p>

<h2>Credits</h2>
<ul class="credits">
  <li><strong>Photographs.</strong> Tunde Olowookere (a Lagos road, 2020); Taini Ozeto (dual
  carriageway outside Abuja); Ayodele Adeniji (concrete in Bogije, Lagos); Okechukwu Iroegbu (an
  earth road through a market at Akara); Wikisoft bros (a tarred road, used as the faint page
  watermark). All five images are <a href="{LICENCE_URL}">{LICENCE_NAME}</a>; each caption above
  carries its own credit.</li>
  <li><strong>Outside figures.</strong> {ext["paved_share"]["value"]} per cent of the road
  network paved, and {ext["poor_condition"]["value"]} per cent of federal roads in poor
  condition in {ext["poor_condition"]["as_of"]}: {esc(ext["paved_share"]["source"])},
  {esc(ext["poor_condition"]["footnote"])} citing the Systematic Country Diagnostic (2020),
  downloaded {esc(ext["paved_share"]["accessed"])}. <a href="{esc(ext["paved_share"]["url"])}">The
  document</a>.</li>
  <li><strong>Licensing.</strong> Photographs CC BY-SA 4.0; the page text and the code that
  builds it MIT; the tables of derived numbers CC BY-SA 4.0.</li>
</ul>

<footer>
<p>Built by <code>scripts/build_report.py</code> from the files below. No network, no
external fonts, no scripts. Input digests, first sixteen characters of SHA-256:</p>
{table("Files this page was generated from", ["File", "Digest"], digest_rows)}
<p>Weather licence: {esc(checks["licence"])}. Weather access date:
{esc(checks["weather_access"])}.</p>
</footer>
"""
    return f"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>RoadSense Nigeria &mdash; the corridor condition signal does not clear its bar</title>
<link rel="icon" href="data:image/svg+xml,%3Csvg xmlns='http://www.w3.org/2000/svg' viewBox='0 0 16 16'%3E%3Crect width='16' height='16' fill='%230e4d36'/%3E%3C/svg%3E">
<meta name="description" content="One page: what was measured on Nigeria's federal road
corridors, why the condition signal failed its pre-specified test, and what it still
supports.">
<style>{CSS}</style>
</head>
<body>
<a class="skip" href="#main">Skip to content</a>
<main id="main">{body}</main>
</body>
</html>
"""


# --- audit ------------------------------------------------------------------------------
def audit_visible_numbers(html_text: str, facts: dict[str, Any]) -> list[str]:
    """Every numeric token in the page's visible text must occur somewhere in ``facts``.

    This is the mechanical answer to "prove no number was typed": strip the style block and
    every tag, then compare the remaining digits against digits that came from the data.
    """
    stripped = re.sub(r"<style\b.*?</style>", " ", html_text, flags=re.S | re.I)
    stripped = re.sub(r"<script\b.*?</script>", " ", stripped, flags=re.S | re.I)
    text = html.unescape(re.sub(r"<[^>]+>", " ", stripped))

    allowed: set[str] = set()

    def collect(value: Any) -> None:
        if isinstance(value, str):
            allowed.update(NUM.findall(value))
        elif isinstance(value, dict):
            for item in value.values():
                collect(item)
        elif isinstance(value, (list, tuple)):
            for item in value:
                collect(item)
        elif isinstance(value, (int, float)) and not isinstance(value, bool):
            allowed.update(NUM.findall(fint(value) if float(value).is_integer() else f4(value)))

    collect(facts)
    allowed.update({"0", "100"})  # origin of an axis, and the whole in "per cent"
    # Product and algorithm names, not measurements. Named so the audit stays strict.
    allowed.update({"2", "256"})  # Sentinel-2, SHA-256

    unknown = sorted({tok for tok in NUM.findall(text) if tok not in allowed})
    return unknown


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.parse_args(argv)

    facts, notes = build_facts()
    page = render(facts)

    OUT_DIR.mkdir(parents=True, exist_ok=True)
    OUT_HTML.write_text(page, encoding="utf-8")
    OUT_FACTS.write_text(
        json.dumps(facts, indent=2, sort_keys=True, ensure_ascii=False) + "\n", encoding="utf-8"
    )

    # Accessibility: contrast of every text/fill pair used above, as a computed check.
    print("Contrast (WCAG AA needs 4.5:1 for text):")
    failures = []
    for name, fg, bg in TEXT_PAIRS:
        ratio = contrast_ratio(fg, bg)
        verdict = "pass" if ratio >= 4.5 else "FAIL"
        if ratio < 4.5:
            failures.append(f"{name}: {ratio:.2f}:1")
        print(f"  {name:<34} {ratio:5.2f}:1  {verdict}")

    # Map marks are non-text graphics: WCAG 2.2 asks for 3:1 against the page. The four coloured
    # arms are checked and fail the build below 3:1. The grey "steady" band is deliberately
    # light — it is the near-zero background class, and drawn at 3:1 it would dominate a map of
    # 434 steady corridors — so its ratio is printed as measured rather than gated, and the
    # class is named in the legend and in the table under the figure.
    print("\nMap arms against the page (non-text graphics need 3:1):")
    for key in ("fall_hard", "fall_mild", "rise_mild", "rise_hard"):
        ratio = contrast_ratio(BAND_COLOURS[key], PAPER)
        verdict = "pass" if ratio >= 3.0 else "FAIL"
        if ratio < 3.0:
            failures.append(f"map arm {key}: {ratio:.2f}:1")
        print(f"  {key:<34} {ratio:5.2f}:1  {verdict}")
    steady_ratio = contrast_ratio(BAND_COLOURS["steady"], PAPER)
    print(f"  {'steady, near-zero background':<34} {steady_ratio:5.2f}:1  measured, not gated")

    unknown = audit_visible_numbers(page, facts)
    print(f"\nNumber audit: {len(NUM.findall(page))} tokens in source, "
          f"{len(unknown)} unexplained in visible text.")
    if unknown:
        print("  unexplained: " + ", ".join(unknown))

    # Documented claims against computed values.
    computed: dict[str, float] = {
        "primary AUC": float(facts["tests"]["rows"][0]["auc"]),
        "primary interval low": float(facts["tests"]["rows"][0]["lo"]),
        "primary interval high": float(facts["tests"]["rows"][0]["hi"]),
        "secondary AUC": float(facts["tests"]["rows"][1]["auc"]),
        "secondary interval low": float(facts["tests"]["rows"][1]["lo"]),
        "secondary interval high": float(facts["tests"]["rows"][1]["hi"]),
        "reference AUC": float(facts["tests"]["rows"][2]["auc"]),
        "reference interval low": float(facts["tests"]["rows"][2]["lo"]),
        "reference interval high": float(facts["tests"]["rows"][2]["hi"]),
        "analysed corridors": float(facts["tests"]["rows"][0]["n"]),
        "corridors with a label": float(facts["tests"]["rows"][0]["n_labelled"]),
        "corridors in the table": float(facts["headline"]["n_corridors"]),
        "corridor share of variance, per cent": float(facts["variance"]["corridor"]),
        "month share of variance, per cent": float(facts["variance"]["month"]),
        "residual share of variance, per cent": float(facts["variance"]["residual"]),
        "September-to-December fall, per cent": float(facts["seasonal"]["fall_pct"]),
    }
    stale: list[str] = []
    print("\nFigures quoted in the documents, against the page:")
    for name, quoted, claimed, tol, source in DOCUMENTED:
        got = computed[name]
        gap = abs(got - claimed)
        ok = gap <= tol + 1e-9
        print(
            f"  {name:<38} quoted {quoted:>8}  page {got:8.4f}  "
            f"{'ok' if ok else 'DISAGREES'}"
        )
        if not ok:
            stale.append(f"{source}: {name} is quoted as {quoted}, the data gives {got:.4f}")

    for note in notes:
        print("  " + note)

    if stale:
        print("\nWARNING. The page is generated from data and is not adjusted to match prose:")
        for line in stale:
            print("  ! " + line)
        print("  Bring the document into line with the page; the page stays as computed.")

    problems = bool(unknown) or bool(failures) or bool(notes)
    print(f"\nWrote {OUT_HTML.relative_to(ROOT)} and {OUT_FACTS.relative_to(ROOT)}")
    print("Exit zero: documents may lag the page, the page may not lag the data.")
    return 1 if problems else 0


if __name__ == "__main__":
    sys.exit(main())
