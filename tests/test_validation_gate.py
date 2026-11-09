"""Tests for the degeneracy gate in `scripts/validate_signal_v2.py` (the T18 failure mode).

T18's score was identically zero by construction: every corridor carried the same value, so the
AUC ranked coverage rather than condition. T19 answered that with a gate that runs before any AUC
and stops the run. These tests pin the gate's behaviour:

* a constant score fails all three criteria;
* a constant score plus float noise still fails -- distinct values at full float precision used to
  be enough to look varied, so the gate also checks the values rounded to 6 decimal places;
* a genuinely varied score passes, so the gate is not simply refusing everything;
* and `main()` returns 2 without writing an AUC when the gate fails, which is the "abort" half of
  the claim. `scripts/validate_signal_v2.py` is importable (`main()` sits behind a `__name__` guard)
  and reads its input and output paths from module constants, so the abort path can be exercised on
  synthetic corridors/condition tables without touching the real data.
"""

from __future__ import annotations

import importlib.util
import json
from pathlib import Path

import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "scripts" / "validate_signal_v2.py"


def _load_script(path: Path, name: str):
    """Import a `scripts/*.py` file as a module without making `scripts` a package."""
    spec = importlib.util.spec_from_file_location(name, path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


validate = _load_script(SCRIPT, "validate_signal_v2_under_test")

MONTHS = [f"2024-{m:02d}" for m in range(1, 13)] + [f"2025-{m:02d}" for m in range(1, 5)]  # 16


# ---------------------------------------------------------------- the gate in isolation
def test_constant_score_fails_the_gate():
    """The T18 failure mode, literally: 850 corridors, one value."""
    gate = validate.degeneracy_gate(np.full(850, 0.42), "constant")

    assert gate["passed"] is False
    assert gate["checks"] == {
        "distinct_ge_50": False,
        "modal_share_lt_20pct": False,
        "sd_gt_1e-6": False,
    }
    assert gate["distinct_values_full_precision"] == 1
    assert gate["share_on_modal_value_rounded_6dp"] == 1.0
    assert gate["modal_value_rounded_6dp"] == 0.42
    assert gate["sd"] == 0.0


def test_constant_score_with_float_noise_still_fails():
    """The reverse trap: float noise manufactures distinct values but no information."""
    rng = np.random.default_rng(20261109)
    score = 0.42 + rng.normal(0.0, 1e-12, 850)

    # the trap is real -- full-precision distinctness alone would have passed this
    assert len(np.unique(score)) > validate.GATE_MIN_DISTINCT

    gate = validate.degeneracy_gate(score, "constant+noise")

    assert gate["passed"] is False
    # the distinctness criterion is fooled -- it counts full-precision values ...
    assert gate["checks"]["distinct_ge_50"] is True
    # ... so the modal share at 6 decimals is what actually closes the trap
    assert gate["distinct_values_rounded_6dp"] == 1
    assert gate["share_on_modal_value_rounded_6dp"] == 1.0
    assert gate["checks"]["modal_share_lt_20pct"] is False


def test_few_distinct_values_fail_even_when_spread_out():
    """Forty units spread over 40 values: plenty of spread, too few distinct values."""
    score = np.repeat(np.linspace(-1.0, 1.0, 40), 10)  # 400 corridors, 40 values, sd >> 1e-6

    gate = validate.degeneracy_gate(score, "quantised")

    assert gate["distinct_values_full_precision"] == 40
    assert gate["checks"]["sd_gt_1e-6"] is True
    assert gate["checks"]["distinct_ge_50"] is False
    assert gate["passed"] is False


def test_varied_score_passes_the_gate():
    rng = np.random.default_rng(20261109)
    score = rng.normal(0.0, 1.0, 850)

    gate = validate.degeneracy_gate(score, "varied")

    assert gate["passed"] is True
    assert all(gate["checks"].values())
    assert gate["distinct_values_rounded_6dp"] >= validate.GATE_MIN_DISTINCT
    assert gate["sd"] > validate.GATE_MIN_SD


# ---------------------------------------------------------------- the gate inside main()
def synthetic_inputs(tmp_path: Path, scores: str) -> tuple[Path, Path]:
    """66 labelled of 120 corridors (the documented count), 16 months, both classes."""
    corridor_rows, condition_rows = [], []
    for primary_class in ("A", "B"):
        for j in range(60):
            cid = f"{primary_class}{j:03d}"
            labelled = 1 if (j % 2 == 0 or j < 6) else 0  # 33 per class -> 66 total
            corridor_rows.append(
                {
                    "corridor_id": cid,
                    "name": f"corridor {cid}",
                    "primary_class": primary_class,
                    "length_km": float(j + 1),
                    "label_events": 3 if labelled else 0,
                }
            )
            for k, month in enumerate(MONTHS):
                if scores == "constant":
                    ndvi_yoy = 0.05
                    ndvi_contrast = 0.10
                else:
                    ndvi_yoy = 0.01 + 0.002 * j
                    ndvi_contrast = 0.10 + (0.0005 + 0.0001 * j) * k
                condition_rows.append(
                    {"corridor_id": cid, "month": month,
                     "ndvi_yoy": ndvi_yoy, "ndvi_contrast": ndvi_contrast}
                )

    corridors_csv = tmp_path / "corridors.csv"
    condition_parquet = tmp_path / "condition.parquet"
    pd.DataFrame(corridor_rows).to_csv(corridors_csv, index=False)
    pd.DataFrame(condition_rows).to_parquet(condition_parquet, index=False)
    return corridors_csv, condition_parquet


def point_at(monkeypatch, tmp_path: Path, corridors_csv: Path, condition_parquet: Path) -> dict:
    out = {
        "json": tmp_path / "validation_v2.json",
        "matched": tmp_path / "validation_v2_matched.csv",
        "exclusions": tmp_path / "validation_v2_exclusions.csv",
    }
    monkeypatch.setattr(validate, "CORRIDORS", corridors_csv)
    monkeypatch.setattr(validate, "CONDITION", condition_parquet)
    monkeypatch.setattr(validate, "OUT_JSON", out["json"])
    monkeypatch.setattr(validate, "OUT_MATCHED", out["matched"])
    monkeypatch.setattr(validate, "OUT_EXCL", out["exclusions"])
    return out


def test_constant_score_aborts_the_run_before_any_auc(tmp_path, monkeypatch, capsys):
    """The T18 table would have produced a confident AUC. With the gate, the run stops at exit 2."""
    corridors_csv, condition_parquet = synthetic_inputs(tmp_path, scores="constant")
    out = point_at(monkeypatch, tmp_path, corridors_csv, condition_parquet)

    code = validate.main()

    stdout = capsys.readouterr().out
    assert code == 2, f"a failed gate must abort with exit 2, got {code}"
    assert "GATE OVERALL: FAIL" in stdout, stdout
    assert "ABORTED" in stdout

    payload = json.loads(out["json"].read_text(encoding="utf-8"))
    assert payload["aborted"] is True
    assert "degeneracy gate" in payload["abort_reason"]
    assert "results" not in payload, "no AUC may be computed when the gate fails"
    for instrument in ("primary_yoy", "secondary_slope", "reference_level"):
        assert payload["degeneracy_gate"][instrument]["all_850"]["passed"] is False
        assert payload["degeneracy_gate"][instrument]["matched"]["passed"] is False
    assert not out["matched"].exists(), "no matched set may be written when the gate fails"


def test_varied_score_passes_the_gate_and_estimates(tmp_path, monkeypatch, capsys):
    """The other half: the same code path must not refuse an informative score."""
    corridors_csv, condition_parquet = synthetic_inputs(tmp_path, scores="varied")
    out = point_at(monkeypatch, tmp_path, corridors_csv, condition_parquet)

    code = validate.main()

    stdout = capsys.readouterr().out
    assert code == 0, f"a passing gate must run to completion, got exit {code}: {stdout[-800:]}"
    assert "GATE OVERALL: PASS" in stdout, stdout

    payload = json.loads(out["json"].read_text(encoding="utf-8"))
    assert payload["aborted"] is False
    assert payload["degeneracy_gate_passed"] is True
    assert payload["counts"]["labelled_total"] == validate.DOCUMENTED_LABELLED
    assert set(payload["results"]) == {"primary_yoy", "secondary_slope", "reference_level"}
    for result in payload["results"].values():
        assert 0.0 <= result["auc_matched"] <= 1.0
        assert result["n_matched"] > 0
    assert out["matched"].exists()


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(__import__("pytest").main([__file__, "-q"]))
