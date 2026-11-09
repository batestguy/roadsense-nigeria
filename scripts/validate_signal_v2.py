"""T19 -- the corrected, pre-specified test of a condition signal against the procurement label.

PRE-SPECIFIED IN `.agent/T19-brief.md` BEFORE THIS FILE WAS RUN.
Do not add a third instrument, do not search features, do not re-match after seeing a number.

Estimand
--------
AUC = P(score of a labelled corridor > score of an unlabelled corridor), higher score = more degraded.
Population: the 850 corridor units in data/interim/corridors.csv, restricted to corridors meeting the
stated minimum-data rule and sitting in a (primary_class, length_quintile) cell that holds both labels.
This is a ranking comparison. It is not a causal effect.

Instruments, exactly two plus one confound reference
----------------------------------------------------
P (primary)   score_yoy   = -mean(ndvi_yoy) over available calendar-month pairs   (min 6 of 10 pairs)
S (secondary) score_slope = -OLS slope of ndvi_contrast on month index            (min 15 non-null months)
R (reference) score_level = -mean(ndvi_contrast), the T18 raw level               (min 15 non-null months)

Why the T18 score is not reused: mean(ndvi_anom2) over a corridor's own months is identically zero
by construction, so it ranked coverage rather than condition (.agent/T18-report.md).

Degeneracy gate -- runs BEFORE any AUC
-------------------------------------
Per instrument, over all 850 corridors and again over the matched analysis set:
  distinct score values                         >= 50
  share of corridors on the modal value         <  20%
  standard deviation across corridors           >  1e-6
Modal share is evaluated on values rounded to 6 decimal places as well as at full float precision;
that is strictly stricter than the literal wording and closes the T18 trap in reverse (float noise
manufacturing distinct values). If ANY instrument fails the gate the run stops: no AUC is computed
for any instrument and the test is reported as invalid. That is the conservative reading of
"stop and report the instrument as invalid", and it cannot flatter the result.

Decision rule, committed before running
--------------------------------------
The bar is AUC >= 0.60 on the matched set with the point estimate >= 0.60 AND the bootstrap lower
bound > 0.50. Anything else is a null result.

Outputs
-------
data/interim/validation_v2.json
data/interim/validation_v2_matched.csv
data/interim/validation_v2_exclusions.csv
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
MIN_YOY_PAIRS = 6
MIN_CONTRAST_MONTHS = 15
DOCUMENTED_LABELLED = 66
N_BANDS = 5
ALPHA = 0.05

GATE_MIN_DISTINCT = 50
GATE_MAX_MODAL_SHARE = 0.20
GATE_MIN_SD = 1e-6

ROOT = Path(__file__).resolve().parents[1]
CORRIDORS = ROOT / "data" / "interim" / "corridors.csv"
CONDITION = ROOT / "data" / "interim" / "condition.parquet"
OUT_JSON = ROOT / "data" / "interim" / "validation_v2.json"
OUT_MATCHED = ROOT / "data" / "interim" / "validation_v2_matched.csv"
OUT_EXCL = ROOT / "data" / "interim" / "validation_v2_exclusions.csv"


# ---------------------------------------------------------------- helpers
def rank_auc(score: np.ndarray, positive: np.ndarray) -> float:
    """Mann-Whitney AUC, 0.5 credit for ties."""
    score = np.asarray(score, dtype=float)
    positive = np.asarray(positive, dtype=bool)
    n1 = int(positive.sum())
    n0 = int((~positive).sum())
    if n1 == 0 or n0 == 0:
        return float("nan")
    r = rankdata(score, method="average")
    return float((r[positive].sum() - n1 * (n1 + 1) / 2.0) / (n1 * n0))


def stratified_bootstrap(score, positive, n_boot=N_BOOT, seed=SEED) -> dict:
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
    }


def permutation_p(score, positive, observed_auc, n_perm=N_PERM, seed=SEED) -> dict:
    rng = np.random.default_rng(seed + 1)
    score = np.asarray(score, dtype=float)
    positive = np.asarray(positive, dtype=bool)
    draws = np.array([rank_auc(score, rng.permutation(positive)) for _ in range(n_perm)])
    return {
        "n_perm": int(n_perm),
        "seed": int(seed + 1),
        "min": float(draws.min()),
        "q025": float(np.percentile(draws, 2.5)),
        "median": float(np.median(draws)),
        "q975": float(np.percentile(draws, 97.5)),
        "max": float(draws.max()),
        "sd": float(draws.std(ddof=1)),
        "p_two_sided": float((np.abs(draws - 0.5) >= abs(observed_auc - 0.5)).mean()),
    }


def degeneracy_gate(score: np.ndarray, label: str) -> dict:
    """The mandatory pre-AUC gate. All three criteria must pass."""
    score = np.asarray(score, dtype=float)
    finite = score[np.isfinite(score)]
    rounded = np.round(finite, 6)
    modal, modal_n = np.unique(rounded, return_counts=True)
    top = int(modal_n.max()) if len(modal_n) else 0
    distinct_full = int(len(np.unique(finite)))
    distinct_6dp = int(len(np.unique(rounded)))
    modal_share_6dp = float(top / len(finite)) if len(finite) else float("nan")
    top_full = int(np.unique(finite, return_counts=True)[1].max()) if len(finite) else 0
    modal_share_full = float(top_full / len(finite)) if len(finite) else float("nan")
    sd = float(finite.std(ddof=1)) if len(finite) > 1 else float("nan")
    checks = {
        "distinct_ge_50": bool(distinct_full >= GATE_MIN_DISTINCT),
        "modal_share_lt_20pct": bool(modal_share_6dp < GATE_MAX_MODAL_SHARE),
        "sd_gt_1e-6": bool(sd > GATE_MIN_SD),
    }
    return {
        "instrument": label,
        "n": int(len(finite)),
        "n_missing": int(len(score) - len(finite)),
        "distinct_values_full_precision": distinct_full,
        "distinct_values_rounded_6dp": distinct_6dp,
        "share_on_modal_value_full_precision": modal_share_full,
        "share_on_modal_value_rounded_6dp": modal_share_6dp,
        "modal_value_rounded_6dp": float(modal[int(np.argmax(modal_n))]) if len(modal) else float("nan"),
        "sd": sd,
        "min": float(finite.min()) if len(finite) else float("nan"),
        "max": float(finite.max()) if len(finite) else float("nan"),
        "thresholds": {
            "distinct_min": GATE_MIN_DISTINCT,
            "modal_share_max": GATE_MAX_MODAL_SHARE,
            "sd_min": GATE_MIN_SD,
        },
        "checks": checks,
        "passed": bool(all(checks.values())),
    }


def cell_balanced_auc(df: pd.DataFrame, col: str) -> dict:
    vals = []
    for _, g in df.groupby(["primary_class", "band"]):
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


def ols_slope_rows(pivot: pd.DataFrame) -> tuple[np.ndarray, np.ndarray]:
    """Per-row OLS slope of y on month index, dropping null cells. Returns (slope, n)."""
    y = pivot.to_numpy(dtype=float)
    mask = np.isfinite(y)
    n = mask.sum(axis=1).astype(float)
    x = np.arange(y.shape[1], dtype=float)[None, :]
    with np.errstate(invalid="ignore", divide="ignore"):
        xbar = np.where(mask, x, 0.0).sum(axis=1) / n
        ybar = np.where(mask, y, 0.0).sum(axis=1) / n
        dx = np.where(mask, x - xbar[:, None], 0.0)
        dy = np.where(mask, y - ybar[:, None], 0.0)
        sxx = (dx * dx).sum(axis=1)
        sxy = (dx * dy).sum(axis=1)
        slope = np.where(sxx > 0, sxy / sxx, np.nan)
    return slope, n


# ---------------------------------------------------------------- load
def main() -> int:
    corridors = pd.read_csv(CORRIDORS)
    condition = pd.read_parquet(CONDITION)

    if set(corridors["corridor_id"]) != set(condition["corridor_id"]):
        raise SystemExit("corridor ids do not align between corridors.csv and condition.parquet")

    corridors["label"] = (corridors["label_events"] > 0).astype(int)
    n_labelled = int(corridors["label"].sum())
    if n_labelled != DOCUMENTED_LABELLED:
        raise SystemExit(
            f"labelled count is {n_labelled}, documented {DOCUMENTED_LABELLED}; stop and reconcile."
        )

    # ---- instrument 1: mean of available year-over-year pairs
    yoy = condition.groupby("corridor_id")["ndvi_yoy"].agg(["count", "mean"])
    yoy = yoy.rename(columns={"count": "n_yoy_pairs", "mean": "mean_yoy"})

    # ---- instrument 2/3: slope and level of monthly ndvi_contrast
    pivot = condition.pivot(index="corridor_id", columns="month", values="ndvi_contrast").sort_index(axis=1)
    slope, n_months = ols_slope_rows(pivot)
    n_months_s = pd.Series(n_months.astype(int), index=pivot.index, name="n_contrast_months")
    slope_s = pd.Series(slope, index=pivot.index, name="slope_contrast")
    mean_contrast = pd.Series(np.nanmean(pivot.to_numpy(dtype=float), axis=1), index=pivot.index, name="mean_contrast")

    df = corridors.merge(yoy, left_on="corridor_id", right_index=True, how="left")
    df = df.merge(n_months_s, left_on="corridor_id", right_index=True, how="left")
    df = df.merge(slope_s, left_on="corridor_id", right_index=True, how="left")
    df = df.merge(mean_contrast, left_on="corridor_id", right_index=True, how="left")

    df["score_yoy"] = -df["mean_yoy"]
    df["score_slope"] = -df["slope_contrast"]
    df["score_level"] = -df["mean_contrast"]

    df["enough_yoy"] = df["n_yoy_pairs"].fillna(0) >= MIN_YOY_PAIRS
    df["enough_months"] = df["n_contrast_months"].fillna(0) >= MIN_CONTRAST_MONTHS

    # ---- bands: quintiles of length within class, over all 850 (population, pre-filter)
    df["band"] = (
        df.groupby("primary_class")["length_km"]
        .transform(lambda s: pd.qcut(s, N_BANDS, labels=False, duplicates="drop"))
        .astype("Int64")
    )
    breakpoints = {
        cls: [float(x) for x in g["length_km"].quantile(np.linspace(0, 1, N_BANDS + 1)).to_numpy()]
        for cls, g in df.groupby("primary_class")
    }

    # ---- ============ DEGENERACY GATE, BEFORE ANY AUC ============
    instruments = [
        ("primary_yoy", "score_yoy"),
        ("secondary_slope", "score_slope"),
        ("reference_level", "score_level"),
    ]

    def matched_for(elig: pd.DataFrame) -> pd.DataFrame:
        cc = (
            elig.groupby(["primary_class", "band"])["label"]
            .agg(n_labelled="sum", n_total="size")
            .reset_index()
        )
        cc["n_unlabelled"] = cc["n_total"] - cc["n_labelled"]
        keep = cc.loc[(cc["n_labelled"] > 0) & (cc["n_unlabelled"] > 0), ["primary_class", "band"]]
        keys = {(r.primary_class, int(r.band)) for r in keep.itertuples()}
        sel = [(c, int(b)) in keys for c, b in zip(elig["primary_class"], elig["band"], strict=False)]
        return elig.loc[sel].copy()

    gates = {}
    gate_pass = True
    for name, col in instruments:
        g_all = degeneracy_gate(df[col].to_numpy(), f"{name} (all 850 corridors)")
        # matched set for this instrument, computed before any AUC so the gate can see it
        elig = df.loc[df["enough_yoy"] if name == "primary_yoy" else df["enough_months"]].copy()
        m = matched_for(elig)
        g_match = degeneracy_gate(m[col].to_numpy(), f"{name} (matched analysis set, n={len(m)})")
        gates[name] = {"all_850": g_all, "matched": g_match}
        if not (g_all["passed"] and g_match["passed"]):
            gate_pass = False

    print("=" * 78)
    print("T19  DEGENERACY GATE  (runs before any AUC; a failure stops the run)")
    print("=" * 78)
    for name, _ in instruments:
        for scope in ("all_850", "matched"):
            g = gates[name][scope]
            print(
                f"{g['instrument']:<52s} n={g['n']:4d} "
                f"distinct={g['distinct_values_full_precision']:4d}/{g['distinct_values_rounded_6dp']:4d} "
                f"modal={100*g['share_on_modal_value_rounded_6dp']:5.1f}% sd={g['sd']:.3g} "
                f"{'PASS' if g['passed'] else 'FAIL'}"
            )
    print(f"GATE OVERALL: {'PASS' if gate_pass else 'FAIL'}")

    def env_block() -> dict:
        return {
            "interpreter": sys.executable,
            "python": platform.python_version(),
            "pandas": pd.__version__,
            "numpy": np.__version__,
            "scipy": scipy.__version__,
        }

    if not gate_pass:
        OUT_JSON.write_text(
            json.dumps(
                {
                    "ticket": "T19",
                    "generated_at": pd.Timestamp.utcnow().isoformat() + "Z",
                    "environment": env_block(),
                    "aborted": True,
                    "abort_reason": "degeneracy gate failed; no AUC computed (T19 brief, mandatory gate)",
                    "degeneracy_gate": gates,
                },
                indent=2,
                default=float,
            ),
            encoding="utf-8",
        )
        print("ABORTED: no AUC computed. Wrote validation_v2.json")
        return 2

    # ---- ============ estimates ============
    results = {}
    all_matched_ids = set()
    excl_rows = []

    for name, col in instruments:
        elig = df.loc[df["enough_yoy"] if name == "primary_yoy" else df["enough_months"]].copy()
        dropped = df.loc[~(df["enough_yoy"] if name == "primary_yoy" else df["enough_months"])].copy()
        m = matched_for(elig)
        unmatched = elig.loc[~elig.index.isin(m.index)]

        for _, r in dropped.iterrows():
            excl_rows.append(
                {
                    "instrument": name,
                    "corridor_id": r["corridor_id"],
                    "name": r["name"],
                    "primary_class": r["primary_class"],
                    "length_km": float(r["length_km"]),
                    "label": int(r["label"]),
                    "n_yoy_pairs": int(r["n_yoy_pairs"]) if pd.notna(r["n_yoy_pairs"]) else 0,
                    "n_contrast_months": int(r["n_contrast_months"]) if pd.notna(r["n_contrast_months"]) else 0,
                    "reason": (
                        f"fewer than {MIN_YOY_PAIRS} year-over-year pairs"
                        if name == "primary_yoy"
                        else f"fewer than {MIN_CONTRAST_MONTHS} non-null contrast months"
                    ),
                }
            )
        for _, r in unmatched.iterrows():
            excl_rows.append(
                {
                    "instrument": name,
                    "corridor_id": r["corridor_id"],
                    "name": r["name"],
                    "primary_class": r["primary_class"],
                    "length_km": float(r["length_km"]),
                    "label": int(r["label"]),
                    "n_yoy_pairs": int(r["n_yoy_pairs"]) if pd.notna(r["n_yoy_pairs"]) else 0,
                    "n_contrast_months": int(r["n_contrast_months"]) if pd.notna(r["n_contrast_months"]) else 0,
                    "reason": "no comparable corridor on the other side of the label (class x length band)",
                }
            )

        pos = (m["label"] == 1).to_numpy()
        score = m[col].to_numpy(dtype=float)
        if not np.isfinite(score).all():
            raise SystemExit(f"{name}: non-finite score in the matched set; no imputation is permitted")

        auc = rank_auc(score, pos)
        boot = stratified_bootstrap(score, pos)
        perm = permutation_p(score, pos, auc)
        auc_un = rank_auc(elig[col].to_numpy(dtype=float), (elig["label"] == 1).to_numpy())
        cell = cell_balanced_auc(m, col)
        cov_col = "n_yoy_pairs" if name == "primary_yoy" else "n_contrast_months"

        results[name] = {
            "score_definition": {
                "primary_yoy": "score = -mean(ndvi_yoy) over available calendar-month pairs; higher = more degraded",
                "secondary_slope": "score = -OLS slope of ndvi_contrast on month index; higher = more degraded",
                "reference_level": "score = -mean(ndvi_contrast); higher = more degraded (T18 reference, confounded)",
            }[name],
            "n_eligible": int(len(elig)),
            "n_matched": int(len(m)),
            "n_matched_labelled": int(pos.sum()),
            "n_matched_unlabelled": int((~pos).sum()),
            "n_excluded_minimum_data": int(len(dropped)),
            "n_excluded_minimum_data_labelled": int(dropped["label"].sum()),
            "n_excluded_no_match": int(len(unmatched)),
            "n_excluded_no_match_labelled": int(unmatched["label"].sum()),
            "auc_matched": auc,
            "ci_low": boot["ci_low"],
            "ci_high": boot["ci_high"],
            "boot_sd": boot["boot_sd"],
            "auc_unmatched": auc_un,
            "permutation_null": perm,
            "cell_balanced": cell,
            "score_by_group": {
                ("labelled" if lab == 1 else "unlabelled"): {
                    "n": int(len(g)),
                    "mean": float(g[col].mean()),
                    "sd": float(g[col].std(ddof=1)),
                    "median": float(g[col].median()),
                    "q1": float(g[col].quantile(0.25)),
                    "q3": float(g[col].quantile(0.75)),
                }
                for lab, g in m.groupby("label")
            },
            "coverage_diagnostic": {
                "column": cov_col,
                "spearman_score_vs_coverage": float(m[col].corr(m[cov_col], method="spearman")),
                "auc_using_coverage_as_the_score": rank_auc(
                    m[cov_col].to_numpy(dtype=float), pos
                ),
                "note": "T18's score was 0.94 correlated with coverage. This checks the same failure mode.",
            },
        }
        all_matched_ids |= set(m["corridor_id"])

    # the direct T18 lesson: does the instrument work among corridors with complete data?
    prim = results["primary_yoy"]
    elig_p = df.loc[df["enough_yoy"]]
    m_p = matched_for(elig_p)
    full = m_p.loc[m_p["n_yoy_pairs"] == m_p["n_yoy_pairs"].max()]
    complete_yoy = {
        "max_pairs": int(m_p["n_yoy_pairs"].max()),
        "n": int(len(full)),
        "n_labelled": int(full["label"].sum()),
        "auc": rank_auc(full["score_yoy"].to_numpy(dtype=float), (full["label"] == 1).to_numpy()),
        "note": "Diagnostic, not the headline. T18's primary AUC fell to 0.5239 on complete-coverage corridors.",
    }

    matched_out = m_p[
        ["corridor_id", "name", "primary_class", "band", "length_km", "label", "label_events",
         "n_yoy_pairs", "mean_yoy", "score_yoy", "n_contrast_months", "slope_contrast",
         "score_slope", "mean_contrast", "score_level"]
    ].sort_values(["primary_class", "band", "label", "corridor_id"])

    payload = {
        "ticket": "T19",
        "generated_at": pd.Timestamp.utcnow().isoformat() + "Z",
        "environment": env_block(),
        "aborted": False,
        "spec": {
            "estimand": "AUC = P(score_labelled > score_unlabelled), higher score = more degraded; a ranking, not a causal effect",
            "labelled_definition": "label_events > 0",
            "instruments": ["primary_yoy", "secondary_slope", "reference_level"],
            "minimum_data": {"primary_yoy": f">= {MIN_YOY_PAIRS} of 10 year-over-year pairs",
                             "secondary_slope": f">= {MIN_CONTRAST_MONTHS} non-null ndvi_contrast months",
                             "reference_level": f">= {MIN_CONTRAST_MONTHS} non-null ndvi_contrast months"},
            "matching": "exact on (primary_class, length_km quintile within class over all 850); retain all corridors in cells holding both labels",
            "bootstrap": f"{N_BOOT} resamples stratified by label, percentile {100*ALPHA/2:.0f}-{100*(1-ALPHA/2):.0f}%",
            "permutations": N_PERM,
            "seed": SEED,
            "no_imputation": True,
            "decision_rule": "bar: matched AUC point estimate >= 0.60 AND bootstrap lower bound > 0.50",
        },
        "counts": {
            "corridors_total": int(len(df)),
            "labelled_total": n_labelled,
            "documented_labelled": DOCUMENTED_LABELLED,
            "labelled_assert_passed": n_labelled == DOCUMENTED_LABELLED,
            "corridors_with_enough_yoy": int(df["enough_yoy"].sum()),
            "corridors_with_enough_months": int(df["enough_months"].sum()),
        },
        "degeneracy_gate": gates,
        "degeneracy_gate_passed": True,
        "results": results,
        "complete_coverage_yoy_diagnostic": complete_yoy,
        "bar": {
            "threshold": 0.60,
            "primary_point_met": bool(prim["auc_matched"] >= 0.60),
            "primary_ci_low_met": bool(prim["ci_low"] > 0.50),
            "primary_cleared": bool(prim["auc_matched"] >= 0.60 and prim["ci_low"] > 0.50),
        },
        "length_band_breakpoints_km": breakpoints,
    }

    OUT_JSON.write_text(json.dumps(payload, indent=2, default=float), encoding="utf-8")
    matched_out.to_csv(OUT_MATCHED, index=False)
    pd.DataFrame(excl_rows).to_csv(OUT_EXCL, index=False)

    print("-" * 78)
    print(f"{'instrument':<20s} {'n':>5s} {'lab':>4s} {'AUC':>7s} {'95% CI':>17s} {'perm p':>7s}")
    for name, _ in instruments:
        r = results[name]
        print(
            f"{name:<20s} {r['n_matched']:5d} {r['n_matched_labelled']:4d} "
            f"{r['auc_matched']:7.4f} [{r['ci_low']:.4f}, {r['ci_high']:.4f}] "
            f"{r['permutation_null']['p_two_sided']:7.2f}"
        )
    print("-" * 78)
    print(f"complete-coverage yoy subset (n={complete_yoy['n']}, lab {complete_yoy['n_labelled']}): "
          f"AUC {complete_yoy['auc']:.4f}")
    for name, _ in instruments:
        r = results[name]
        print(f"  {name:<18s} spearman(score,coverage) {r['coverage_diagnostic']['spearman_score_vs_coverage']:+.3f} | "
              f"AUC(coverage) {r['coverage_diagnostic']['auc_using_coverage_as_the_score']:.4f} | "
              f"cell-balanced {r['cell_balanced']['cell_balanced_auc']:.4f} over "
              f"{r['cell_balanced']['cells_with_both_labels']} cells "
              f"[{r['cell_balanced']['cell_auc_min']:.2f}, {r['cell_balanced']['cell_auc_max']:.2f}]")
    print("-" * 78)
    print(f"BAR 0.60: point {'MET' if payload['bar']['primary_point_met'] else 'NOT MET'}; "
          f"lower bound > 0.50 {'MET' if payload['bar']['primary_ci_low_met'] else 'NOT MET'}; "
          f"cleared {'YES' if payload['bar']['primary_cleared'] else 'NO'}")
    print(f"wrote {OUT_JSON.name}, {OUT_MATCHED.name}, {OUT_EXCL.name}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
