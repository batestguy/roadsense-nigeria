"""T18 -- does a procurement label separate corridors on the condition signal?

PRE-SPECIFIED TEST. This file implements the brief in `.agent/T18-brief.md` as written.
Do not add features, do not re-tune, do not drop corridors to improve the number.

Estimand
--------
AUC = P(score of a labelled corridor > score of an unlabelled corridor), where
score = -mean(ndvi_anom2) over the corridor's non-null months (higher = more degraded).
Population: the 850 corridor units in data/interim/corridors.csv.
This is a ranking comparison, not a causal effect.

Specification fixed before looking at any coefficient
------------------------------------------------------
1. Labelled := label_events > 0. Asserted against the documented 66.
2. score      := -mean(ndvi_anom2) over non-null months.
3. Bands      := quintiles of length_km computed WITHIN primary_class, over all 850
                 corridors (the population, before any eligibility filter).
4. Matching   := coarsened exact matching on (primary_class, length_band). A cell is
                 retained only if it holds >=1 labelled AND >=1 unlabelled corridor;
                 every corridor in a retained cell is kept (no 1:1 subsampling).
5. Minimum data := >=12 non-null months of ndvi_anom2.
6. Interval   := 2,000 bootstrap resamples, resampling corridors, stratified by label,
                 percentile interval. Seed 20261109.
7. Reference  := -mean(ndvi_contrast), same orientation, on the matched set. This is the
                 raw (un-anomalised) level F22 shows is confounded by land cover, road
                 size and season.

Outputs
-------
data/interim/validation.json            full results
data/interim/validation_matched.csv     corridor-level analysis set
data/interim/validation_exclusions.csv  every excluded corridor and the reason
"""

from __future__ import annotations

import json
import platform
import sys
from pathlib import Path

import numpy as np
import pandas as pd
import scipy
from scipy.stats import rankdata

# ---------------------------------------------------------------- constants
SEED = 20261109
N_BOOT = 2000
N_PERM = 100
MIN_MONTHS = 12
DOCUMENTED_LABELLED = 66
N_BANDS = 5
ALPHA = 0.05

ROOT = Path(__file__).resolve().parents[1]
CORRIDORS = ROOT / "data" / "interim" / "corridors.csv"
CONDITION = ROOT / "data" / "interim" / "condition.parquet"
OUT_JSON = ROOT / "data" / "interim" / "validation.json"
OUT_MATCHED = ROOT / "data" / "interim" / "validation_matched.csv"
OUT_EXCL = ROOT / "data" / "interim" / "validation_exclusions.csv"


# ---------------------------------------------------------------- helpers
def rank_auc(score: np.ndarray, positive: np.ndarray) -> float:
    """Mann-Whitney AUC with 0.5 credit for ties. positive: bool array."""
    score = np.asarray(score, dtype=float)
    positive = np.asarray(positive, dtype=bool)
    n1 = int(positive.sum())
    n0 = int((~positive).sum())
    if n1 == 0 or n0 == 0:
        return float("nan")
    r = rankdata(score, method="average")
    return float((r[positive].sum() - n1 * (n1 + 1) / 2.0) / (n1 * n0))


def stratified_bootstrap_ci(
    score: np.ndarray, positive: np.ndarray, n_boot: int, seed: int
) -> dict:
    """Resample corridors with replacement, stratified by label, fixed group sizes."""
    rng = np.random.default_rng(seed)
    score = np.asarray(score, dtype=float)
    positive = np.asarray(positive, dtype=bool)
    idx1 = np.flatnonzero(positive)
    idx0 = np.flatnonzero(~positive)
    n1, n0 = len(idx1), len(idx0)
    draws = np.empty(n_boot, dtype=float)
    for b in range(n_boot):
        take = np.concatenate(
            [rng.choice(idx1, size=n1, replace=True), rng.choice(idx0, size=n0, replace=True)]
        )
        draws[b] = rank_auc(score[take], positive[take])
    lo, hi = np.percentile(draws, [100 * ALPHA / 2, 100 * (1 - ALPHA / 2)])
    return {
        "n_boot": int(n_boot),
        "seed": int(seed),
        "ci_low": float(lo),
        "ci_high": float(hi),
        "boot_mean": float(draws.mean()),
        "boot_sd": float(draws.std(ddof=1)),
        "draws": draws,
    }


def label_permutation_null(
    score: np.ndarray, positive: np.ndarray, n_perm: int, seed: int
) -> dict:
    """Shuffle labels within the analysis set; the real AUC should sit outside this."""
    rng = np.random.default_rng(seed + 1)
    score = np.asarray(score, dtype=float)
    positive = np.asarray(positive, dtype=bool)
    draws = np.empty(n_perm, dtype=float)
    for i in range(n_perm):
        draws[i] = rank_auc(score, rng.permutation(positive))
    return {
        "n_perm": int(n_perm),
        "seed": int(seed + 1),
        "min": float(draws.min()),
        "q025": float(np.percentile(draws, 2.5)),
        "median": float(np.median(draws)),
        "q975": float(np.percentile(draws, 97.5)),
        "max": float(draws.max()),
        "mean": float(draws.mean()),
        "sd": float(draws.std(ddof=1)),
        "draws": draws,
    }


def cell_balanced_auc(df: pd.DataFrame, col: str) -> dict:
    """Sensitivity: average the within-cell AUC equally across matched cells, so the
    large primary-class cells do not dominate. Cell must hold both labels."""
    vals = []
    for (_cls, _band), g in df.groupby(["primary_class", "band"]):
        pos = (g["label"] == 1).to_numpy()
        if pos.sum() == 0 or (~pos).sum() == 0:
            continue
        vals.append(rank_auc(g[col].to_numpy(), pos))
    vals = np.asarray(vals, dtype=float)
    return {
        "cells_with_both_labels": int(len(vals)),
        "cell_balanced_auc": float(vals.mean()),
        "cell_auc_min": float(vals.min()),
        "cell_auc_max": float(vals.max()),
        "cell_aucs": [float(v) for v in vals],
    }


# ---------------------------------------------------------------- load
def main() -> int:
    corridors = pd.read_csv(CORRIDORS)
    condition = pd.read_parquet(CONDITION)

    if set(corridors["corridor_id"]) != set(condition["corridor_id"]):
        raise SystemExit("corridor ids do not align between corridors.csv and condition.parquet")

    corridors["label"] = (corridors["label_events"] > 0).astype(int)

    # ---- 1. labelled count, asserted against the documented figure
    n_labelled = int(corridors["label"].sum())
    if n_labelled != DOCUMENTED_LABELLED:
        raise SystemExit(
            f"labelled count is {n_labelled}, documented {DOCUMENTED_LABELLED}; "
            "stop and reconcile rather than proceed (brief, Stop and report)."
        )

    # ---- 2/4. one score per corridor, minimum-data rule
    months = condition.groupby("corridor_id")["ndvi_anom2"].agg(["count", "mean", "median"])
    months = months.rename(columns={"count": "n_months", "mean": "mean_anom2", "median": "median_anom2"})
    contrast = condition.groupby("corridor_id")["ndvi_contrast"].agg(["count", "mean"])
    contrast = contrast.rename(columns={"count": "n_months_contrast", "mean": "mean_contrast"})

    df = corridors.merge(months, left_on="corridor_id", right_index=True, how="left")
    df = df.merge(contrast, left_on="corridor_id", right_index=True, how="left")

    df["score"] = -df["mean_anom2"]           # higher = more degraded
    df["score_median"] = -df["median_anom2"]  # sensitivity only
    df["score_contrast"] = -df["mean_contrast"]  # reference (confounded, F22)

    df["enough_months"] = df["n_months"].fillna(0) >= MIN_MONTHS
    excluded_min = df.loc[~df["enough_months"]].copy()

    # ---- 3. length bands, quintiles within class over the full population
    df["band"] = (
        df.groupby("primary_class")["length_km"]
        .transform(lambda s: pd.qcut(s, N_BANDS, labels=False, duplicates="drop"))
        .astype("Int64")
    )
    breakpoints = {
        cls: [float(x) for x in g["length_km"].quantile(np.linspace(0, 1, N_BANDS + 1)).to_numpy()]
        for cls, g in df.groupby("primary_class")
    }

    eligible = df.loc[df["enough_months"]].copy()

    # ---- matching: retain cells holding both labels
    cell_counts = (
        eligible.groupby(["primary_class", "band"])["label"]
        .agg(n_labelled="sum", n_total="size")
        .reset_index()
    )
    cell_counts["n_unlabelled"] = cell_counts["n_total"] - cell_counts["n_labelled"]
    cell_counts["keep"] = (cell_counts["n_labelled"] > 0) & (cell_counts["n_unlabelled"] > 0)
    keep_keys = {
        (r.primary_class, int(r.band))
        for r in cell_counts.loc[cell_counts["keep"]].itertuples()
    }
    eligible["matched"] = [
        (c, int(b)) in keep_keys for c, b in zip(eligible["primary_class"], eligible["band"], strict=False)
    ]

    matched = eligible.loc[eligible["matched"]].copy()
    excluded_no_match = eligible.loc[~eligible["matched"]].copy()

    n_lab_matched = int(matched["label"].sum())
    n_unl_matched = int(len(matched) - n_lab_matched)
    if n_lab_matched < 30 or n_unl_matched < 30:
        raise SystemExit(
            f"matching left {n_lab_matched} labelled / {n_unl_matched} unlabelled; "
            "below the 30-per-side stop rule."
        )

    # ---- 5/6. estimates
    boot_matched = stratified_bootstrap_ci(
        matched["score"].to_numpy(), matched["label"].to_numpy() == 1, N_BOOT, SEED
    )
    boot_unmatched = stratified_bootstrap_ci(
        eligible["score"].to_numpy(), eligible["label"].to_numpy() == 1, N_BOOT, SEED
    )
    boot_ref = stratified_bootstrap_ci(
        matched["score_contrast"].to_numpy(), matched["label"].to_numpy() == 1, N_BOOT, SEED
    )

    auc_matched = rank_auc(matched["score"].to_numpy(), matched["label"].to_numpy() == 1)
    auc_unmatched = rank_auc(eligible["score"].to_numpy(), eligible["label"].to_numpy() == 1)
    auc_ref = rank_auc(matched["score_contrast"].to_numpy(), matched["label"].to_numpy() == 1)

    # ---- sanity: label shuffle
    perm = label_permutation_null(
        matched["score"].to_numpy(), matched["label"].to_numpy() == 1, N_PERM, SEED
    )
    obs_dev = abs(auc_matched - 0.5)
    perm_p = float((np.abs(perm["draws"] - 0.5) >= obs_dev).mean())

    # ---- sensitivity (specification only, no new features)
    sens_median = rank_auc(
        matched["score_median"].to_numpy(), matched["label"].to_numpy() == 1
    )
    sens_no_motorway = matched.loc[matched["primary_class"] != "motorway"]
    sens_no_mw = rank_auc(
        sens_no_motorway["score"].to_numpy(), sens_no_motorway["label"].to_numpy() == 1
    )
    sens_cell = cell_balanced_auc(matched, "score")

    # ---- diagnostics that could falsify the primary score.
    # anom2 = value - corridor_mean - month_mean + grand_mean, so summing over a
    # corridor's own non-null months cancels the corridor term. A corridor with full
    # coverage therefore has mean(anom2) = 0 by construction; the only durable
    # cross-corridor variation left is WHICH months are missing. These three checks
    # quantify how much of the primary AUC that is.
    complete = matched.loc[matched["n_months"] == matched["n_months"].max()]
    auc_complete = rank_auc(complete["score"].to_numpy(), complete["label"].to_numpy() == 1)
    auc_coverage = rank_auc(matched["n_months"].to_numpy(), matched["label"].to_numpy() == 1)
    rho = float(matched["score"].corr(matched["n_months"], method="spearman"))

    # the score is a plateau plus float noise: count the plateau explicitly rather
    # than trusting nunique(), which is sensitive to the 15th significant digit
    modal = float(matched["score"].round(9).value_counts().index[0])
    at_plateau = (matched["score"] - modal).abs() < 1e-9
    plateau = {
        "modal_score": modal,
        "corridors_at_modal_score": int(at_plateau.sum()),
        "share_at_modal_score": float(at_plateau.mean()),
        "labelled_at_modal_score": int((at_plateau & (matched["label"] == 1)).sum()),
        "unlabelled_at_modal_score": int((at_plateau & (matched["label"] == 0)).sum()),
        "corridors_off_plateau": int((~at_plateau).sum()),
        "labelled_off_plateau": int(((~at_plateau) & (matched["label"] == 1)).sum()),
        "unlabelled_off_plateau": int(((~at_plateau) & (matched["label"] == 0)).sum()),
    }

    diagnostics = {
        "score_distinct_values": int(matched["score"].nunique()),
        "score_distinct_values_note": (
            "unreliable: differs between the in-memory array and the CSV round-trip because "
            "the spread sits in the 15th significant digit. Use the plateau counts."
        ),
        "plateau": plateau,
        "score_sd": float(matched["score"].std(ddof=1)),
        "score_iqr": float(matched["score"].quantile(0.75) - matched["score"].quantile(0.25)),
        "score_abs_median": float(matched["score"].abs().median()),
        "full_coverage_months": int(matched["n_months"].max()),
        "corridors_with_full_coverage": int(len(complete)),
        "corridors_with_full_coverage_labelled": int(complete["label"].sum()),
        "auc_full_coverage_subset": float(auc_complete),
        "auc_using_month_coverage_as_the_score": float(auc_coverage),
        "spearman_score_vs_month_coverage": rho,
        "share_of_rank_variance_with_coverage": rho**2,
        "interpretation": (
            "The pre-specified score is arithmetically near-degenerate: two-way centring "
            "removes each corridor's own mean, so a corridor observed for all months scores "
            "~0 regardless of condition. The surviving spread is a function of which months "
            "are missing. If the coverage-only AUC is close to the primary AUC, the primary "
            "number is a coverage ranking, not a condition ranking."
        ),
    }

    # ---- balance table
    balance = (
        cell_counts.assign(
            group=np.where(
                cell_counts["keep"],
                "matched",
                np.where(cell_counts["n_labelled"] == 0, "dropped: no labelled", "dropped: no unlabelled"),
            )
        )
        .sort_values(["primary_class", "band"])
        .reset_index(drop=True)
    )

    # ---- exclusion lists
    excl_rows = []
    for _, r in excluded_min.iterrows():
        excl_rows.append(
            {
                "corridor_id": r["corridor_id"],
                "name": r["name"],
                "primary_class": r["primary_class"],
                "length_km": float(r["length_km"]),
                "label": int(r["label"]),
                "n_months": int(r["n_months"]) if pd.notna(r["n_months"]) else 0,
                "reason": "fewer than 12 non-null months",
            }
        )
    for _, r in excluded_no_match.iterrows():
        excl_rows.append(
            {
                "corridor_id": r["corridor_id"],
                "name": r["name"],
                "primary_class": r["primary_class"],
                "length_km": float(r["length_km"]),
                "label": int(r["label"]),
                "n_months": int(r["n_months"]),
                "reason": "no comparable corridor on the other side of the label (class x length band)",
            }
        )
    excl = pd.DataFrame(excl_rows)

    # ---- score summary by group
    def group_summary(frame: pd.DataFrame) -> dict:
        out = {}
        for lab, g in frame.groupby("label"):
            out["labelled" if lab == 1 else "unlabelled"] = {
                "n": int(len(g)),
                "score_mean": float(g["score"].mean()),
                "score_sd": float(g["score"].std(ddof=1)),
                "score_median": float(g["score"].median()),
                "score_q1": float(g["score"].quantile(0.25)),
                "score_q3": float(g["score"].quantile(0.75)),
                "n_months_min": int(g["n_months"].min()),
                "n_months_mean": float(g["n_months"].mean()),
            }
        return out

    results = {
        "ticket": "T18",
        "generated_at": pd.Timestamp.utcnow().isoformat() + "Z",
        "environment": {
            "interpreter": sys.executable,
            "python": platform.python_version(),
            "pandas": pd.__version__,
            "numpy": np.__version__,
            "scipy": scipy.__version__,
        },
        "spec": {
            "labelled_definition": "label_events > 0",
            "score": "score = -mean(ndvi_anom2) over non-null months; higher = more degraded",
            "reference_score": "score = -mean(ndvi_contrast) over non-null months (confounded, F22)",
            "bands": f"{N_BANDS} quantiles of length_km within primary_class, computed on all 850 corridors",
            "matching": "exact on (primary_class, length_band); retain all corridors in cells holding both labels",
            "minimum_months": MIN_MONTHS,
            "bootstrap": f"{N_BOOT} resamples, stratified by label, percentile {int(100*ALPHA/2)}-{int(100*(1-ALPHA/2))}%",
            "seed": SEED,
        },
        "counts": {
            "corridors_total": int(len(df)),
            "labelled_total": n_labelled,
            "documented_labelled": DOCUMENTED_LABELLED,
            "labelled_assert_passed": n_labelled == DOCUMENTED_LABELLED,
            "eligible_after_minimum_months": int(len(eligible)),
            "excluded_minimum_months": int(len(excluded_min)),
            "matched_total": int(len(matched)),
            "matched_labelled": n_lab_matched,
            "matched_unlabelled": n_unl_matched,
            "excluded_no_match": int(len(excluded_no_match)),
            "excluded_no_match_labelled": int(excluded_no_match["label"].sum()),
        },
        "length_band_breakpoints_km": breakpoints,
        "primary": {
            "matched_auc": auc_matched,
            "matched_ci_low": boot_matched["ci_low"],
            "matched_ci_high": boot_matched["ci_high"],
            "matched_boot_sd": boot_matched["boot_sd"],
        },
        "unmatched": {
            "auc": auc_unmatched,
            "ci_low": boot_unmatched["ci_low"],
            "ci_high": boot_unmatched["ci_high"],
            "boot_sd": boot_unmatched["boot_sd"],
            "n_total": int(len(eligible)),
            "n_labelled": int(eligible["label"].sum()),
        },
        "reference_raw_contrast": {
            "matched_auc": auc_ref,
            "ci_low": boot_ref["ci_low"],
            "ci_high": boot_ref["ci_high"],
            "boot_sd": boot_ref["boot_sd"],
            "note": "raw level, no anomaly removal; F22 shows it tracks season and land cover",
        },
        "permutation_null": {k: v for k, v in perm.items() if k != "draws"},
        "permutation_p_two_sided": perm_p,
        "score_summary_matched": group_summary(matched),
        "score_summary_unmatched": group_summary(eligible),
        "sensitivity": {
            "median_instead_of_mean_auc": float(sens_median),
            "drop_motorway_class_auc": float(sens_no_mw),
            "drop_motorway_n": int(len(sens_no_motorway)),
            "cell_balanced_auc": sens_cell,
        },
        "diagnostics": diagnostics,
        "bar": {
            "threshold": 0.60,
            "met": bool(auc_matched >= 0.60),
            "met_on_ci_low": bool(boot_matched["ci_low"] >= 0.60),
        },
    }

    balance.to_csv(OUT_MATCHED.parent / "validation_balance.csv", index=False)

    matched_out = matched[
        [
            "corridor_id",
            "name",
            "primary_class",
            "band",
            "length_km",
            "label",
            "label_events",
            "n_months",
            "mean_anom2",
            "score",
            "mean_contrast",
            "score_contrast",
        ]
    ].sort_values(["primary_class", "band", "label", "corridor_id"])
    matched_out.to_csv(OUT_MATCHED, index=False)
    excl.to_csv(OUT_EXCL, index=False)

    # json-safe (strip numpy scalars)
    def clean(o):
        if isinstance(o, dict):
            return {k: clean(v) for k, v in o.items()}
        if isinstance(o, (list, tuple)):
            return [clean(v) for v in o]
        if isinstance(o, (np.floating,)):
            return float(o)
        if isinstance(o, (np.integer,)):
            return int(o)
        if isinstance(o, (np.bool_,)):
            return bool(o)
        return o

    OUT_JSON.write_text(json.dumps(clean(results), indent=2), encoding="utf-8")

    # ---- console summary (this is what the report quotes)
    print("=" * 72)
    print("T18  AUC of a procurement label on the corridor condition signal")
    print("=" * 72)
    print(f"corridors            {len(df)}   labelled {n_labelled} (documented {DOCUMENTED_LABELLED})")
    print(f"minimum-data excl.   {len(excluded_min)} corridors (< {MIN_MONTHS} non-null months)")
    print(f"matched set          {len(matched)}  ({n_lab_matched} labelled / {n_unl_matched} unlabelled)")
    print(f"no-match excluded    {len(excluded_no_match)}  ({int(excluded_no_match['label'].sum())} labelled)")
    print("-" * 72)
    print(f"1. MATCHED AUC       {auc_matched:.4f}  95% CI [{boot_matched['ci_low']:.4f}, {boot_matched['ci_high']:.4f}]")
    print(f"2. UNMATCHED AUC     {auc_unmatched:.4f}  95% CI [{boot_unmatched['ci_low']:.4f}, {boot_unmatched['ci_high']:.4f}]")
    print(f"3. RAW-CONTRAST AUC  {auc_ref:.4f}  95% CI [{boot_ref['ci_low']:.4f}, {boot_ref['ci_high']:.4f}]  (reference, confounded)")
    print("-" * 72)
    print(f"shuffle null (n={N_PERM}): min {perm['min']:.4f}  q2.5 {perm['q025']:.4f}  "
          f"median {perm['median']:.4f}  q97.5 {perm['q975']:.4f}  max {perm['max']:.4f}  "
          f"sd {perm['sd']:.4f}")
    print(f"two-sided permutation p = {perm_p:.2f}")
    print(f"BAR 0.60: point {'MET' if auc_matched >= 0.60 else 'NOT MET'}; "
          f"CI lower bound {'MET' if boot_matched['ci_low'] >= 0.60 else 'NOT MET'}")
    print("-" * 72)
    print("DIAGNOSTIC -- is the score a condition measure or a coverage artefact?")
    print(f"  distinct score values      {diagnostics['score_distinct_values']} "
          f"(float-noise sensitive; see plateau)")
    print(f"  at one identical score     {plateau['corridors_at_modal_score']} of {len(matched)} "
          f"({100*plateau['share_at_modal_score']:.0f}%)  "
          f"labelled {plateau['labelled_at_modal_score']}, unlabelled {plateau['unlabelled_at_modal_score']}")
    print(f"  off the plateau            {plateau['corridors_off_plateau']} "
          f"(labelled {plateau['labelled_off_plateau']}, unlabelled {plateau['unlabelled_off_plateau']})")
    print(f"  score sd / |median|        {diagnostics['score_sd']:.3g} / {diagnostics['score_abs_median']:.3g}")
    print(f"  spearman(score, months)    {rho:.3f}")
    print(f"  AUC using months as score  {auc_coverage:.4f}")
    print(f"  AUC, full-coverage subset  {auc_complete:.4f}  (n={len(complete)}, "
          f"labelled {int(complete['label'].sum())})")
    print("-" * 72)
    print("balance (class x length band; labelled / unlabelled, kept?)")
    for _, r in balance.iterrows():
        flag = "" if bool(r["keep"]) else f"   <-- {r['group']}"
        print(f"  {r['primary_class']:9s} band {int(r['band'])}   "
              f"{int(r['n_labelled']):3d} / {int(r['n_unlabelled']):3d}{flag}")
    print("-" * 72)
    print(f"sensitivity: median score {sens_median:.4f} | "
          f"drop motorway {sens_no_mw:.4f} (n={len(sens_no_motorway)}) | "
          f"cell-balanced {sens_cell['cell_balanced_auc']:.4f} over "
          f"{sens_cell['cells_with_both_labels']} cells")
    print(f"wrote {OUT_JSON.name}, {OUT_MATCHED.name}, {OUT_EXCL.name}, validation_balance.csv")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
