"""Turn per-tile NDVI/NDBI contrast into one honest condition series per corridor-month.

The question this answers is narrow. A raw contrast level ranks a corridor by *when* it was
observed as much as by its condition: findings F22 measured every contrast column falling 42%
between 2024-09 and 2024-12 with no road having changed. This script removes the calendar and
proves, twice and with printed output, that it removed only the calendar.

The correction
--------------
**Primary — within-month anomaly.** For each month, subtract that month's median across corridors:

    anom(corridor, month) = contrast(corridor, month) - median_month(contrast)

F22 prescribes a per-corridor same-calendar-month baseline. That cannot be fitted here: the series
spans 22 months, so each calendar month occurs at most twice per corridor, and a two-point baseline
is noise. The seasonal swing, by contrast, is national and simultaneous (F22 measured it in the
national mean), so removing the month's central value removes the calendar from every corridor at
once while keeping the differences *between corridors within that month* — the only part that can
carry condition.

**Secondary — year-over-year change**, only where both ends exist: `value(m) - value(m - 12)`.
Months without a 12-month predecessor are null, never filled.

**Forbidden:** month-over-month differences. F22 is explicit that a Sep->Dec move is the weather.

What this does NOT fix
----------------------
Centring within a month removes time confounding, not land-cover confounding. The national mean is
+0.13 against Lagos +0.008..+0.023 (F19/F22), and that gap is still present in the anomaly. Use the
anomaly for *change*, never to compare the level of condition between corridors in different
land-cover settings.

Gates
-----
The imagery manifest (`complete: true`) is the input contract. If it says `complete: false`, this
script refuses to write a final table and exits 2. `--allow-partial` builds and validates against the
incomplete input and writes a table explicitly labelled provisional (exit 3). It never writes a file
called `condition.parquet` from incomplete input.

Exit codes: 0 complete, 1 the data is wrong, 2 refused (incomplete input, no flag), 3 partial
written.

Provenance: input table, input manifest sha256, the aggregation rule, and every null count are
recorded in `condition*.manifest.json` beside the parquet.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import sys
from datetime import UTC, datetime
from pathlib import Path

import numpy as np
import pandas as pd

#: Input columns this script needs. Anything absent is a hard failure, not a silent skip.
REQUIRED = [
    "corridor_id",
    "corridor_name",
    "tile_x",
    "tile_y",
    "month",
    "resolution_m",
    "pixels_core",
    "pixels_ring",
    "ndvi_core",
    "ndvi_ring",
    "ndvi_contrast",
    "ndbi_core",
    "ndbi_ring",
    "ndbi_contrast",
]

KEY = ["corridor_id", "tile_x", "tile_y", "month"]

#: Months the input is expected to cover, and pairs a complete series would yield (2024-09..2026-06).
EXPECTED_MONTHS = "2024-09..2026-06"
EXPECTED_YOY_PAIRS = 10

#: Below this, the anomaly has erased cross-corridor spread and the correction must be reported as
#: failed. Fixed before the measurement (T16 brief); do not lower it to make a run pass.
SD_RATIO_MIN = 0.5

EXIT_COMPLETE, EXIT_WRONG, EXIT_REFUSED, EXIT_PARTIAL = 0, 1, 2, 3


def fail(msg: str, code: int = EXIT_WRONG) -> int:
    print(f"FAIL: {msg}", file=sys.stderr)
    return code


def sha256(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as fh:
        for chunk in iter(lambda: fh.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def prev_year(month: str) -> str:
    """'2025-09' -> '2024-09'."""
    return str(pd.Period(month, "M") - 12)


def _weighted_mean(values: pd.Series, weights: pd.Series) -> float:
    """Mean over the non-null values, weighted by their pixel counts.

    A tile's mean is over its own pixels, so pooling the tiles of one corridor is a pixel-weighted
    mean — not an unweighted mean of ratios, which would let a 47-pixel tile outvote a 1,394-pixel
    one. Returns NaN when no tile in the group has a usable value; nothing is imputed.
    """
    usable = values.notna() & weights.notna() & (weights > 0)
    total = float(weights[usable].sum())
    if total <= 0:
        return float("nan")
    return float((values[usable] * weights[usable]).sum() / total)


def aggregate_to_corridor_month(df: pd.DataFrame) -> pd.DataFrame:
    """Collapse (corridor, tile, month) rows to one row per (corridor, month).

    Aggregation rule, stated so a reader can reproduce it:

    * `ndvi_contrast` is the **road-length-weighted mean of the per-tile contrasts**, weighted by
      `pixels_core` (the rasterised road footprint, a road-length proxy inside the tile). Each tile's
      contrast compares verge and carriageway *on the same ground*; averaging those measurements
      weights a long stretch of road more than a short one. `*_contrast_unweighted` is the plain mean
      of the same tile contrasts (this is what F22 measured over rows) and `*_contrast_pooled` is
      `ring - core` after pooling bands across tiles.
    * Pooling the bands is kept only as a labelled alternative: mixing verge pixels from a rural tile
      with carriageway pixels from an urban one can produce a contrast that no part of the corridor
      has. Measured on one 2-tile corridor the pooled value was 0.017 against a tile-mean 0.005.
    * `ndvi_core`, `ndvi_ring` (and NDBI) remain pixel-weighted band means across tiles, weighted by
      `pixels_core` and `pixels_ring`.
    """
    keys = ["corridor_id", "corridor_name", "month"]

    work = df.copy()
    for band, weight in (
        ("ndvi_core", "pixels_core"),
        ("ndvi_ring", "pixels_ring"),
        ("ndbi_core", "pixels_core"),
        ("ndbi_ring", "pixels_ring"),
    ):
        usable = work[band].notna() & (work[weight] > 0)
        work[f"_{band}_v"] = (work[band] * work[weight]).where(usable, 0.0)
        work[f"_{band}_w"] = work[weight].where(usable, 0.0)

    for col in ("ndvi_contrast", "ndbi_contrast"):
        usable = work[col].notna() & (work["pixels_core"] > 0)
        work[f"_{col}_v"] = (work[col] * work["pixels_core"]).where(usable, 0.0)
        work[f"_{col}_w"] = work["pixels_core"].where(usable, 0.0)

    agg = work.groupby(keys, as_index=False).agg(
        n_tiles=("tile_x", "size"),
        n_tiles_usable=("ndvi_contrast", lambda s: int(s.notna().sum())),
        n_tiles_usable_ndbi=("ndbi_contrast", lambda s: int(s.notna().sum())),
        pixels_core=("pixels_core", "sum"),
        pixels_ring=("pixels_ring", "sum"),
        ndvi_contrast_unweighted=("ndvi_contrast", "mean"),
        ndbi_contrast_unweighted=("ndbi_contrast", "mean"),
    )
    summed = [
        *(f"_{b}_{s}" for b in ("ndvi_core", "ndvi_ring", "ndbi_core", "ndbi_ring")
          for s in ("v", "w")),
        *(f"_{c}_{s}" for c in ("ndvi_contrast", "ndbi_contrast") for s in ("v", "w")),
    ]
    sums = work.groupby(keys, as_index=False).agg(**{c: (c, "sum") for c in summed})
    out = agg.merge(sums, on=keys, how="left")

    for band in ("ndvi_core", "ndvi_ring", "ndbi_core", "ndbi_ring"):
        weight = out[f"_{band}_w"]
        out[band] = np.where(
            weight > 0, out[f"_{band}_v"] / weight.replace(0, np.nan), np.nan
        )
    out["ndvi_contrast_pooled"] = out["ndvi_ring"] - out["ndvi_core"]
    out["ndbi_contrast_pooled"] = out["ndbi_ring"] - out["ndbi_core"]

    for index in ("ndvi", "ndbi"):
        weight = out[f"_{index}_contrast_w"]
        weighted = out[f"_{index}_contrast_v"] / weight.replace(0, np.nan)
        # A tile with no road pixels carries no length weight; fall back to the plain mean rather
        # than discarding a usable measurement, and only where such a value exists.
        out[f"{index}_contrast"] = np.where(
            weight > 0, weighted, out[f"{index}_contrast_unweighted"]
        )

    drop = [c for c in out.columns if c.startswith("_")]
    return out.drop(columns=drop)


def add_anomaly(out: pd.DataFrame) -> pd.DataFrame:
    """Two centrings, both kept: within-month only, and corridor + month (two-way).

    ``anom`` subtracts the month's median across corridors. It removes the calendar and nothing
    else, so a corridor's land cover, terrain and surface type stay in the number — F22's warning
    that the national mean (+0.13) and Lagos (+0.008..+0.023) differ by more than season.

    ``anom2`` subtracts the corridor's own mean and the month's mean and adds the grand mean back:
    ``value - corridor_mean - month_mean + grand_mean``. Eighteen to twenty-two observations per
    corridor is a usable estimate of a corridor mean, which a same-calendar-month baseline (at most
    two observations) never was. It removes the corridor's level and the national seasonal swing at
    the same time.

    ``anom2`` centres on means because the variance decomposition is defined on means; ``anom``
    stays on the median the brief prescribes, which resists a few extreme corridors. Nulls
    propagate — no corridor mean is imputed for a corridor with no usable month.
    """
    for index in ("ndvi", "ndbi"):
        col = f"{index}_contrast"
        out[f"{index}_month_median"] = out["month"].map(out.groupby("month")[col].median())
        out[f"{index}_month_mean"] = out["month"].map(out.groupby("month")[col].mean())
        out[f"{index}_corridor_mean"] = out["corridor_id"].map(
            out.groupby("corridor_id")[col].mean())
        grand_mean = float(out[col].mean())
        out[f"{index}_anom"] = out[col] - out[f"{index}_month_median"]
        out[f"{index}_anom2"] = (
            out[col] - out[f"{index}_corridor_mean"] - out[f"{index}_month_mean"] + grand_mean
        )
    return out


def add_yoy(out: pd.DataFrame) -> pd.DataFrame:
    """Year-over-year change against the same calendar month one year earlier.

    Null where the earlier month has no row for that corridor, or where either end is unusable.
    Nothing is interpolated, so a corridor with a missing 2025-09 simply has no 2025-09 pair.
    """
    out["month_prev"] = out["month"].map(prev_year)
    # `pairs` is keyed by each row's own month relabelled `month_prev`; a row joins it with its
    # own month_prev, which is exactly the same calendar month one year earlier.
    pairs = out[["corridor_id", "month", "ndvi_contrast", "ndbi_contrast"]].rename(
        columns={"month": "month_prev", "ndvi_contrast": "ndvi_prev", "ndbi_contrast": "ndbi_prev"}
    )
    out = out.drop(columns=["ndvi_prev", "ndbi_prev"], errors="ignore")
    out = out.merge(pairs, on=["corridor_id", "month_prev"], how="left")

    out["ndvi_yoy"] = out["ndvi_contrast"] - out["ndvi_prev"]
    out["ndbi_yoy"] = out["ndbi_contrast"] - out["ndbi_prev"]
    return out.drop(columns=["month_prev", "ndvi_prev", "ndbi_prev"])


def variance_decomposition(out: pd.DataFrame) -> dict:
    """How much of the raw variation is corridor level, month level, and neither.

    This is the non-tautological measurement. The within-month centring preserves cross-corridor
    spread exactly (subtracting one constant per month), so its sd ratio cannot fail; this asks the
    question that can: how much of the raw variation is even a candidate for condition?

    Sums of squares on the raw values: between corridors, between months, and the two-way residual
    (the sum of squares of ``anom2``). On a balanced panel the three add to the total exactly; this
    panel has 140 empty cells, so ``overlap_share`` reports the shortfall instead of hiding it.
    """
    result: dict = {}
    for index in ("ndvi", "ndbi"):
        col = f"{index}_contrast"
        d = out[["corridor_id", "month", col]].dropna()
        grand = float(d[col].mean())
        by_corridor = d.groupby("corridor_id")[col]
        by_month = d.groupby("month")[col]
        ss_total = float(((d[col] - grand) ** 2).sum())
        ss_corridor = float((by_corridor.size() * (by_corridor.mean() - grand) ** 2).sum())
        ss_month = float((by_month.size() * (by_month.mean() - grand) ** 2).sum())
        ss_resid = float(
            ((d[col] - by_corridor.transform("mean") - by_month.transform("mean") + grand) ** 2)
            .sum()
        )
        result[index] = {
            "n_obs": int(len(d)),
            "grand_mean": grand,
            "sd_total": float(d[col].std(ddof=1)),
            "ss_total": ss_total,
            "share_corridor": ss_corridor / ss_total,
            "share_month": ss_month / ss_total,
            "share_residual": ss_resid / ss_total,
            "overlap_share": 1.0 - (ss_corridor + ss_month + ss_resid) / ss_total,
            "sd_residual": float(np.sqrt(ss_resid / (len(d) - 1))),
        }
    return result


def seasonal_table(out: pd.DataFrame, rowwise: pd.DataFrame | None = None) -> pd.DataFrame:
    """Per month: the raw centre, the anomaly centre, the cross-corridor spread, and its ratio.

    ``rowwise`` carries the unweighted mean *row* contrast per month, which is how F22 was measured
    (3,146 tile rows per month). It is included so this table can be checked against F22 rather than
    quietly disagreeing with it.
    """
    rows = []
    for month, grp in out.groupby("month", sort=True):
        row: dict = {"month": month, "corridors": int(grp["corridor_id"].nunique())}
        for index in ("ndvi", "ndbi"):
            raw = grp[f"{index}_contrast"]
            anom = grp[f"{index}_anom"]
            sd_raw = float(raw.std(ddof=1))
            sd_anom = float(anom.std(ddof=1))
            row[f"{index}_rowwise_mean"] = (
                float(rowwise.loc[month, f"{index}_contrast"])
                if rowwise is not None and month in rowwise.index else float("nan")
            )
            row[f"{index}_raw_mean"] = float(raw.mean())
            row[f"{index}_raw_median"] = float(raw.median())
            row[f"{index}_anom_median"] = float(anom.median())
            row[f"{index}_raw_q1"] = float(raw.quantile(0.25))
            row[f"{index}_raw_q3"] = float(raw.quantile(0.75))
            row[f"{index}_anom_mean"] = float(anom.mean())
            row[f"{index}_sd_raw"] = sd_raw
            row[f"{index}_sd_anom"] = sd_anom
            row[f"{index}_sd_ratio"] = sd_anom / sd_raw if sd_raw > 0 else float("nan")
            row[f"{index}_n_obs"] = int(raw.notna().sum())
        rows.append(row)
    return pd.DataFrame(rows)


def swing(table: pd.DataFrame, start: str, end: str, index: str = "ndvi") -> dict:
    """Raw and anomaly movement between two months, for the F22 comparison."""
    a = table[table["month"] == start]
    b = table[table["month"] == end]
    if a.empty or b.empty:
        return {"start": start, "end": end, "available": False}
    raw_a = float(a[f"{index}_raw_mean"].iloc[0])
    raw_b = float(b[f"{index}_raw_mean"].iloc[0])
    anom_a = float(a[f"{index}_anom_mean"].iloc[0])
    anom_b = float(b[f"{index}_anom_mean"].iloc[0])
    return {
        "start": start,
        "end": end,
        "available": True,
        "raw_start": raw_a,
        "raw_end": raw_b,
        "raw_change": raw_b - raw_a,
        "raw_change_pct": (raw_b - raw_a) / raw_a * 100 if raw_a else float("nan"),
        "anom_start": anom_a,
        "anom_end": anom_b,
        "anom_change": anom_b - anom_a,
    }


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--input", default="data/features/imagery_r10.parquet")
    ap.add_argument("--input-manifest", default="data/features/imagery_r10.manifest.json")
    ap.add_argument("--out-dir", default="data/interim")
    ap.add_argument("--allow-partial", action="store_true",
                    help="build and validate against an incomplete imagery input; output is "
                         "labelled provisional and is NOT written as condition.parquet")
    args = ap.parse_args()

    src = Path(args.input)
    src_manifest = Path(args.input_manifest)
    if not src.exists():
        return fail(f"input table not found: {src}", EXIT_REFUSED)
    if not src_manifest.exists():
        return fail(f"input manifest not found: {src_manifest} — no provenance, no table",
                    EXIT_REFUSED)

    manifest = json.loads(src_manifest.read_text(encoding="utf-8"))
    complete = bool(manifest.get("complete"))
    missing_months = list(manifest.get("months_missing") or [])
    expected_corridors = int(manifest.get("expected_corridors_per_month") or 850)

    print(f"input   {src}")
    print(f"manifest complete={complete}  months_covered={len(manifest.get('months_covered', []))}"
          f"  months_missing={missing_months}")

    if int(manifest.get("duplicate_keys", -1)) != 0:
        return fail(f"input manifest reports {manifest.get('duplicate_keys')} duplicate keys")
    if int(manifest.get("resolution_m", 0)) != 10:
        return fail(f"input is {manifest.get('resolution_m')} m; the contrast feature requires 10 m "
                    "(F19: 40 m flips the contrast sign on 20.6% of corridor-months)")

    if not complete and not args.allow_partial:
        return fail(
            f"imagery input is incomplete: {len(missing_months)} months missing "
            f"({', '.join(missing_months)}). Refusing to write a final condition table. "
            "Re-run when the backfill has merged them, or pass --allow-partial to build a "
            "provisional table for validation only.",
            EXIT_REFUSED,
        )

    df = pd.read_parquet(src)
    print(f"rows    {len(df)}  corridors={df['corridor_id'].nunique()}  "
          f"months={df['month'].nunique()}")

    missing_cols = [c for c in REQUIRED if c not in df.columns]
    if missing_cols:
        return fail(f"input table is missing columns: {missing_cols}")

    dup = int(df.duplicated(subset=KEY).sum())
    if dup:
        return fail(f"{dup} duplicate (corridor, tile, month) keys in the input")
    print("no duplicate (corridor, tile, month) keys")

    resolutions = sorted(df["resolution_m"].unique().tolist())
    if resolutions != [10]:
        return fail(f"resolution_m values are {resolutions}, expected [10]")

    per_month = df.groupby("month")["corridor_id"].nunique()
    short = {m: int(n) for m, n in per_month.items() if int(n) != expected_corridors}
    if short:
        return fail(f"these months do not cover {expected_corridors} corridors: {short}")
    print(f"every month covers {expected_corridors} corridors")

    out = aggregate_to_corridor_month(df)
    out = add_anomaly(out)
    out = add_yoy(out)

    dup_cm = int(out.duplicated(subset=["corridor_id", "month"]).sum())
    if dup_cm:
        return fail(f"{dup_cm} duplicate (corridor, month) keys after aggregation")

    table = seasonal_table(out, rowwise=df.groupby("month")[
        ["ndvi_contrast", "ndbi_contrast"]].mean())

    # ---- Proof 1: the season is gone -------------------------------------------------------
    print("\nProof 1 — national centre by month (raw level vs within-month anomaly)")
    print(f"{'month':8} {'ndvi_raw':>9} {'ndvi_anom':>10} {'ndbi_raw':>9} {'ndbi_anom':>10}")
    for _, r in table.iterrows():
        print(f"{r['month']:8} {r['ndvi_raw_mean']:9.4f} {r['ndvi_anom_mean']:10.5f} "
              f"{r['ndbi_raw_mean']:9.4f} {r['ndbi_anom_mean']:10.5f}")

    # The median-centring the brief prescribes makes the anomaly *median* exactly zero each
    # month; the anomaly *mean* is only near zero, because mean - median is the skew of the
    # cross-corridor distribution. Both are measured, and the residual is reported, not hidden.
    seasonal = {}
    for index in ("ndvi", "ndbi"):
        raw_mean_sd = float(table[f"{index}_raw_mean"].std(ddof=1))
        anom_mean_sd = float(table[f"{index}_anom_mean"].std(ddof=1))
        seasonal[index] = {
            "sd_across_months_raw_mean": raw_mean_sd,
            "sd_across_months_anom_mean": anom_mean_sd,
            "seasonal_amplitude_removed_pct": (1 - anom_mean_sd / raw_mean_sd) * 100
            if raw_mean_sd else float("nan"),
            "max_abs_anom_mean": float(table[f"{index}_anom_mean"].abs().max()),
            "max_abs_anom_median": float(table[f"{index}_anom_median"].abs().max()),
            "raw_mean_range": float(table[f"{index}_raw_mean"].max()
                                    - table[f"{index}_raw_mean"].min()),
        }
        print(f"{index}: sd across months of the national mean — raw {raw_mean_sd:.5f}, "
              f"anomaly {anom_mean_sd:.5f} "
              f"({seasonal[index]['seasonal_amplitude_removed_pct']:.0f}% of the seasonal swing "
              f"removed); max |anomaly mean| {seasonal[index]['max_abs_anom_mean']:.5f}, "
              f"max |anomaly median| {seasonal[index]['max_abs_anom_median']:.1e}")

    # F22 replication: the same months, measured the way F22 measured them (unweighted mean over
    # the 3,146 tile rows), next to the corridor-level pooled figure this table uses.
    f22_months = ["2024-09", "2024-10", "2024-11", "2024-12"]
    rep = table[table["month"].isin(f22_months)]
    print("\nF22 replication over 2024-09..2024-12 (tile-row mean vs corridor road-length-weighted "
          "mean):")
    for _, r in rep.iterrows():
        print(f"  {r['month']}  rows {r['ndvi_rowwise_mean']:.4f}  "
              f"corridor {r['ndvi_raw_mean']:.4f}  anomaly {r['ndvi_anom_mean']:+.5f}")
    first, last = rep.iloc[0], rep.iloc[-1]
    print(f"  Sep->Dec on tile rows: {first['ndvi_rowwise_mean']:.4f} -> "
          f"{last['ndvi_rowwise_mean']:.4f} "
          f"({(last['ndvi_rowwise_mean'] - first['ndvi_rowwise_mean']) / first['ndvi_rowwise_mean'] * 100:+.1f}%)"
          f"   [F22 measured +0.1458 -> +0.0838, -42%]")
    print(f"  Sep->Dec on corridor means: {first['ndvi_raw_mean']:.4f} -> "
          f"{last['ndvi_raw_mean']:.4f} "
          f"({(last['ndvi_raw_mean'] - first['ndvi_raw_mean']) / first['ndvi_raw_mean'] * 100:+.1f}%)")
    print(f"  Sep->Dec on the anomaly: {first['ndvi_anom_mean']:+.5f} -> "
          f"{last['ndvi_anom_mean']:+.5f}")

    # ---- Variance decomposition: the measurement that is not tautological --------------------
    decomp = variance_decomposition(out)
    print("\nVariance decomposition of the raw value (additive corridor + month):")
    for index, v in decomp.items():
        print(f"  {index}: total sd {v['sd_total']:.5f} | corridor {v['share_corridor'] * 100:5.1f}% "
              f"| month {v['share_month'] * 100:5.1f}% | residual {v['share_residual'] * 100:5.1f}% "
              f"(residual sd {v['sd_residual']:.5f}; overlap {v['overlap_share'] * 100:+.2f}%)")
    absorbed = {}
    for index in ("ndvi", "ndbi"):
        cm_raw = out.groupby("corridor_id")[f"{index}_contrast"].mean()
        cm_anom = out.groupby("corridor_id")[f"{index}_anom"].mean()
        cm_anom2 = out.groupby("corridor_id")[f"{index}_anom2"].mean()
        absorbed[index] = {
            "max_abs_corridor_mean_anom2": float(cm_anom2.abs().max()),
            "max_abs_month_mean_anom2": float(
                out.groupby("month")[f"{index}_anom2"].mean().abs().max()),
            "spearman_corridor_mean_raw_vs_anom": float(
                cm_raw.corr(cm_anom, method="spearman")),
            "spearman_corridor_mean_raw_vs_anom2": float(
                cm_raw.corr(cm_anom2, method="spearman")),
        }
        print(f"  {index} two-way: max |corridor mean of anom2| "
              f"{absorbed[index]['max_abs_corridor_mean_anom2']:.1e}, max |month mean of anom2| "
              f"{absorbed[index]['max_abs_month_mean_anom2']:.1e}; corridor-level persistence "
              f"spearman(raw, anom) {absorbed[index]['spearman_corridor_mean_raw_vs_anom']:.3f} "
              f"vs (raw, anom2) {absorbed[index]['spearman_corridor_mean_raw_vs_anom2']:.3f}")
    print("  (corridor means of anom2 are not exactly zero: 140 empty cells make the panel "
          "unbalanced, so the additive formula leaves a small residual corridor effect)")

    swings = [
        swing(table, "2024-09", "2024-12"),
        swing(table, "2025-09", "2025-12"),
        swing(table, "2024-09", "2024-12", index="ndbi"),
    ]
    print("\nSep->Dec swing, raw vs anomaly (F22 measured a 42% raw drop at tile level)")
    for s in swings:
        if not s["available"]:
            print(f"  {s['start']} -> {s['end']}: month not present in this input")
            continue
        print(f"  {s['start']} -> {s['end']}: raw {s['raw_start']:+.4f} -> {s['raw_end']:+.4f} "
              f"({s['raw_change_pct']:+.1f}%)   anomaly {s['anom_start']:+.5f} -> "
              f"{s['anom_end']:+.5f} ({s['anom_change']:+.5f})")

    # ---- Proof 2: an arithmetic identity, not evidence --------------------------------------
    print("\nProof 2 — ARITHMETIC IDENTITY, NOT EVIDENCE: subtracting one constant per month cannot")
    print("change the cross-corridor sd or the within-month rank order. Printed only to confirm the")
    print("centring is exactly one constant per month; it says nothing about what survived.")
    print(f"{'month':8} {'sd_raw':>9} {'sd_anom':>9} {'ratio':>7}  {'q1':>8} {'median':>8} {'q3':>8}")
    for _, r in table.iterrows():
        print(f"{r['month']:8} {r['ndvi_sd_raw']:9.5f} {r['ndvi_sd_anom']:9.5f} "
              f"{r['ndvi_sd_ratio']:7.4f}  {r['ndvi_raw_q1']:8.4f} "
              f"{r['ndvi_raw_median']:8.4f} {r['ndvi_raw_q3']:8.4f}")

    min_ratio = float(table[["ndvi_sd_ratio", "ndbi_sd_ratio"]].min().min())
    print(f"minimum sd(anomaly)/sd(raw) across months and both indices: {min_ratio:.4f}")
    if not np.isfinite(min_ratio) or min_ratio < SD_RATIO_MIN:
        print(f"FAIL: the anomaly erased cross-corridor spread (ratio {min_ratio:.4f} < "
              f"{SD_RATIO_MIN}). Stopping without writing a table; do not lower the threshold.",
              file=sys.stderr)
        return EXIT_WRONG

    # Within a month the anomaly is the raw value minus a constant, so it can only preserve the
    # ordering exactly. Measured rather than asserted, because a mis-keyed merge would break it.
    order_ok = True
    for month, grp in out.groupby("month"):
        if grp["ndvi_contrast"].notna().sum() > 2 and grp["ndvi_anom"].notna().sum() > 2:
            rho = grp["ndvi_contrast"].corr(grp["ndvi_anom"], method="spearman")
            if not (rho > 0.9999):
                order_ok = False
                print(f"WARNING {month}: within-month rank correlation raw vs anomaly is {rho:.4f}")
    print(f"within-month rank order preserved in every month: {order_ok}")

    # Does the corrected series carry a persistent corridor signature at all? If between-corridor
    # spread of the corridor means is no bigger than within-corridor month-to-month noise, the
    # anomaly is a per-corridor random walk and nothing downstream will find structure in it.
    # This cannot tell condition from land cover - only labels can - so it is a floor, not a proof.
    persistence = {}
    for index in ("ndvi", "ndbi"):
        col = f"{index}_anom"
        by_corridor = out.groupby("corridor_id")[col]
        between = float(by_corridor.mean().std(ddof=1))
        within = float((out[col] - by_corridor.transform("mean")).std(ddof=1))
        persistence[index] = {"sd_between_corridors": between, "sd_within_corridor": within,
                              "ratio": between / within if within else float("nan")}
        print(f"{index}: sd between corridors {between:.5f} vs within corridor {within:.5f} "
              f"(ratio {persistence[index]['ratio']:.2f})")

    # Does the choice of tile aggregation change the ranking? If the three variants agree, the
    # numbers above do not depend on a judgement call made in this script.
    sens = {}
    for index in ("ndvi", "ndbi"):
        base = out[f"{index}_contrast"]
        sens[index] = {
            "spearman_weighted_vs_unweighted": float(
                base.corr(out[f"{index}_contrast_unweighted"], method="spearman")),
            "spearman_weighted_vs_pooled": float(
                base.corr(out[f"{index}_contrast_pooled"], method="spearman")),
            "max_abs_weighted_minus_unweighted": float(
                (base - out[f"{index}_contrast_unweighted"]).abs().max()),
        }
        print(f"{index} aggregation: spearman(weighted, unweighted) "
              f"{sens[index]['spearman_weighted_vs_unweighted']:.4f}, "
              f"(weighted, pooled) {sens[index]['spearman_weighted_vs_pooled']:.4f}, "
              f"max gap {sens[index]['max_abs_weighted_minus_unweighted']:.4f}")

    # Is the monthly median dominated by a handful of corridors? Report the quartiles and how far
    # the median moves when the extreme 2.5% each side is trimmed, as a fraction of the IQR.
    dominance = []
    for month, grp in out.groupby("month"):
        raw = grp["ndvi_contrast"].dropna()
        if len(raw) < 20:
            continue
        lo, hi = raw.quantile(0.025), raw.quantile(0.975)
        trimmed = raw[(raw >= lo) & (raw <= hi)].median()
        iqr = float(raw.quantile(0.75) - raw.quantile(0.25))
        dominance.append({
            "month": month,
            "median": float(raw.median()),
            "median_trimmed": float(trimmed),
            "iqr": iqr,
            "shift_over_iqr": abs(float(trimmed) - float(raw.median())) / iqr if iqr else float("nan"),
        })
    dom = pd.DataFrame(dominance)
    print(f"median may be a cluster? max |trimmed-median|/IQR = "
          f"{dom['shift_over_iqr'].max():.4f} (0 means a stable centre)")

    # ---- Coverage --------------------------------------------------------------------------
    yoy = out[out["ndvi_yoy"].notna()]
    pairs = (
        yoy.assign(month_prev=yoy["month"].map(prev_year))
        .groupby(["month_prev", "month"], as_index=False)
        .agg(corridors=("corridor_id", "nunique"))
    )
    print(f"\ncoverage: {out['corridor_id'].nunique()} corridors x {out['month'].nunique()} months "
          f"= {len(out)} rows")
    print(f"year-over-year pairs present: {len(pairs)} "
          f"(a complete 2024-09..2026-06 series yields {EXPECTED_YOY_PAIRS})")
    for _, r in pairs.iterrows():
        print(f"  {r['month_prev']} -> {r['month']}: {int(r['corridors'])} corridors")
    corridors_with_yoy = int(yoy["corridor_id"].nunique())
    corridors_without_yoy = int(out["corridor_id"].nunique() - corridors_with_yoy)
    print(f"corridors with at least one yoy pair: {corridors_with_yoy}; "
          f"without any: {corridors_without_yoy}")
    nulls = {c: int(out[c].isna().sum()) for c in sorted(out.columns)}
    print("nulls per column: " + ", ".join(f"{k}={v}" for k, v in nulls.items()))
    unusable = out[out["ndvi_contrast"].isna()]
    print(f"corridor-months with no usable ndvi contrast: {len(unusable)} across "
          f"{int(unusable['corridor_id'].nunique())} corridors — left null, not imputed")
    null_rows = (
        unusable[["corridor_id", "corridor_name", "month", "n_tiles", "n_tiles_usable",
                  "n_tiles_usable_ndbi", "pixels_core"]]
        .sort_values(["corridor_id", "month"])
        .reset_index(drop=True)
    )
    null_months = null_rows.groupby("corridor_id")["month"].agg(["size", "min", "max"])
    repeat = null_months[null_months["size"] > 1]
    print(f"distinct corridors with a null month: {len(null_months)}; "
          f"null in more than one month: {len(repeat)}; "
          f"worst {int(null_months['size'].max()) if len(null_months) else 0} months")
    for cid, r in repeat.head(10).iterrows():
        print(f"  {cid}: {int(r['size'])} null months ({r['min']}..{r['max']})")

    # ---- Write -----------------------------------------------------------------------------
    out_dir = Path(args.out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    if complete:
        stem, status = "condition", "final"
    else:
        stem, status = "condition.provisional", "provisional"
        stale = out_dir / "condition.parquet"
        if stale.exists():
            print(f"WARNING {stale} already exists and was NOT written by this run; it may predate "
                  "a manifest change. Verify its manifest before use.", file=sys.stderr)

    parquet = out_dir / f"{stem}.parquet"
    manifest_out = out_dir / f"{stem}.manifest.json"
    nulls_csv = out_dir / f"{stem}.nulls.csv"
    null_rows.to_csv(nulls_csv, index=False)
    ordered = [
        "corridor_id", "corridor_name", "month",
        "ndvi_contrast", "ndbi_contrast",
        "ndvi_contrast_unweighted", "ndbi_contrast_unweighted",
        "ndvi_contrast_pooled", "ndbi_contrast_pooled",
        "ndvi_core", "ndvi_ring", "ndbi_core", "ndbi_ring",
        "ndvi_anom", "ndbi_anom", "ndvi_anom2", "ndbi_anom2", "ndvi_yoy", "ndbi_yoy",
        "ndvi_month_median", "ndbi_month_median", "ndvi_month_mean", "ndbi_month_mean",
        "ndvi_corridor_mean", "ndbi_corridor_mean",
        "n_tiles", "n_tiles_usable", "n_tiles_usable_ndbi", "pixels_core", "pixels_ring",
    ]
    out = out[ordered].sort_values(["corridor_id", "month"]).reset_index(drop=True)
    out.to_parquet(parquet, index=False)

    payload = {
        "generated_at": datetime.now(UTC).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "artifact": "condition",
        "status": status,
        "provisional": not complete,
        "provisional_reason": (f"imagery manifest complete=false; {len(missing_months)} months "
                               f"missing: {', '.join(missing_months)}") if not complete else None,
        "do_not_publish": not complete,
        "input": {
            "table": str(src),
            "table_sha256": sha256(src),
            "manifest": str(src_manifest),
            "manifest_sha256": sha256(src_manifest),
            "imagery_complete": complete,
            "months_covered": manifest.get("months_covered"),
            "months_missing": missing_months,
            "expected_months": manifest.get("expected_months", EXPECTED_MONTHS),
        },
        "method": {
            "primary": "within-month anomaly (anom): value - median across corridors for that month",
            "two_way": "anom2: value - corridor_mean - month_mean + grand_mean; removes the "
                       "corridor's own level (land cover, terrain, surface) and the national "
                       "monthly swing together, from 16-22 observations per corridor",
            "secondary": "year-over-year difference against the same calendar month one year "
                         "earlier; null where no earlier month exists; no imputation",
            "forbidden": "month-over-month difference (F22: Sep->Dec movement is seasonal)",
            "sd_ratio_note": "a within-month additive shift preserves cross-corridor sd exactly; "
                             "the sd ratio is arithmetic, not evidence",
            "corridor_tile_aggregation": "road-length-weighted mean of per-tile contrasts "
                                         "(weight pixels_core); *_contrast_unweighted is the plain "
                                         "mean over tiles, *_contrast_pooled is ring - core after "
                                         "pooling bands across tiles",
            "sd_ratio_min": SD_RATIO_MIN,
        },
        "output": {"table": str(parquet), "sha256": sha256(parquet), "rows": len(out)},
        "coverage": {
            "corridors": int(out["corridor_id"].nunique()),
            "months": int(out["month"].nunique()),
            "rows": len(out),
            "months_present": sorted(out["month"].unique().tolist()),
            "duplicate_corridor_month_keys": dup_cm,
            "yoy_pairs_present": len(pairs),
            "yoy_pairs_expected_when_complete": EXPECTED_YOY_PAIRS,
            "yoy_pairs": pairs.to_dict(orient="records"),
            "corridors_with_any_yoy_pair": corridors_with_yoy,
            "corridors_without_yoy_pair": corridors_without_yoy,
            "corridor_months_without_usable_ndvi": int(len(unusable)),
            "corridors_with_an_unusable_month": int(unusable["corridor_id"].nunique()),
            "null_months_per_corridor_max": int(null_months["size"].max()) if len(null_months) else 0,
            "corridors_null_in_more_than_one_month": int(len(repeat)),
            "null_corridor_months_file": str(nulls_csv),
            "nulls_per_column": nulls,
        },
        "proofs": {
            "variance_decomposition": decomp,
            "two_way_absorption": absorbed,
            "proof1_season_removed": {
                "seasonal": seasonal,
                "sep_dec_swings": swings,
                "f22_replication_2024_09_to_2024_12": {
                    "ndvi_rowwise_mean_by_month": {
                        str(m): float(v) for m, v in
                        table.set_index("month")["ndvi_rowwise_mean"].items()
                    },
                },
            },
            "arithmetic_identity_not_evidence": {
                "claim": "within-month centring cannot change cross-corridor sd or within-month "
                         "rank order, because it subtracts one constant per month",
                "min_sd_ratio": min_ratio,
                "within_month_rank_order_preserved": order_ok,
                "persistence": persistence,
                "aggregation_sensitivity": sens,
                "months": table.to_dict(orient="records"),
            },
            "median_stability": dom.to_dict(orient="records"),
        },
    }
    manifest_out.write_text(json.dumps(payload, indent=2), encoding="utf-8")

    print(f"\nwrote {parquet}  rows={len(out)}  status={status}")
    print(f"manifest {manifest_out}")
    if not complete:
        print("this table is PROVISIONAL: the imagery input is missing "
              f"{len(missing_months)} months. Do not publish it as the final condition table.",
              file=sys.stderr)
        return EXIT_PARTIAL
    return EXIT_COMPLETE


if __name__ == "__main__":
    raise SystemExit(main())
