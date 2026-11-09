"""Tests for `scripts/collect_imagery.py` -- the checks that make the collected table usable.

Each test builds synthetic windows in `tmp_path` (parquet, no network, no real data) and calls the
script's `main()` in-process. Assertions are on the exit code **and** the message, because a test
that only checks "does not raise" passes just as well with the guard deleted.

The scenarios, in the order the brief ranks them:

1. month drift -- one physical month under two spellings (`"2025-01"` / `"2025-01 "`)
2. a short month -- and the same input accepted when the gap is named
3. an unexpected corridor gap -- must fail even when a *different* corridor is allowed
4. partial months -- `--allow-partial` writes and exits 3, without it nothing is written
5. clean input -- the happy path, pinned so a future guard cannot over-trigger silently
"""

from __future__ import annotations

import importlib.util
import json
import sys
from pathlib import Path

import pandas as pd
import pytest

ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "scripts" / "collect_imagery.py"
TILE = ((11, 22),)  # one tile per (corridor, month) keeps the duplicate keys obvious


def _load_script(path: Path, name: str):
    """Import a `scripts/*.py` file as a module without making `scripts` a package."""
    spec = importlib.util.spec_from_file_location(name, path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


collect = _load_script(SCRIPT, "collect_imagery_under_test")


def frame(months, corridors, tiles=TILE) -> pd.DataFrame:
    """A minimal valid window: every required column, consistent dtypes, resolution 10."""
    recs = []
    for month in months:
        for corridor in corridors:
            for tx, ty in tiles:
                recs.append(
                    {
                        "corridor_id": corridor,
                        "corridor_name": f"name-{corridor}",
                        "tile_x": tx,
                        "tile_y": ty,
                        "month": month,
                        "resolution_m": 10,
                        "item_id": f"{corridor}-{tx}-{ty}-{month}",
                        "pixels_core": 100,
                        "pixels_ring": 200,
                        "ndvi_core": 0.30,
                        "ndvi_ring": 0.50,
                        "ndvi_contrast": 0.20,
                        "ndbi_core": 0.10,
                        "ndbi_ring": 0.05,
                        "ndbi_contrast": 0.05,
                    }
                )
    return pd.DataFrame(recs)


def write_window(cache: Path, run_id: str, rows: pd.DataFrame) -> None:
    out = cache / run_id / "imagery_r10.parquet"
    out.parent.mkdir(parents=True, exist_ok=True)
    rows.to_parquet(out, index=False)


def run(
    tmp_path: Path,
    monkeypatch,
    cache: Path,
    *,
    expect_months: str,
    corridors: int,
    extra_args: list[str] | None = None,
    out_name: str = "imagery_r10.parquet",
) -> tuple[int, Path, Path]:
    """Call `main()` with synthetic arguments; return (exit code, output path, manifest path)."""
    out = tmp_path / out_name
    manifest = tmp_path / "imagery_r10.manifest.json"
    argv = [
        "collect_imagery.py",
        "--cache", str(cache),
        "--out", str(out),
        "--manifest", str(manifest),
        "--expect-months", expect_months,
        "--expect-corridors", str(corridors),
        *(extra_args or []),
    ]
    monkeypatch.setattr(sys, "argv", argv)
    return collect.main(), out, manifest


# ---------------------------------------------------------------- 1. month drift
def test_trailing_space_month_is_caught_as_a_duplicate(tmp_path, monkeypatch, capsys):
    """Two windows, one physical month, two spellings: `2025-01` and `2025-01 `.

    Before the strip was added, the cross-window duplicate check compared the strings, saw two
    different months, and reported a clean table with the month counted twice.
    """
    cache = tmp_path / "cache"
    write_window(cache, "run-a", frame(["2025-01"], ["c1", "c2"]))
    write_window(cache, "run-b", frame(["2025-01 "], ["c1", "c2"]))

    code, out, manifest = run(
        tmp_path, monkeypatch, cache, expect_months="2025-01..2025-01", corridors=2
    )

    err = capsys.readouterr().err
    assert code == collect.EXIT_WRONG, f"expected the duplicate to fail the run, got exit {code}"
    assert "duplicate" in err.lower(), err
    assert "ACROSS windows" in err, err
    assert not out.exists(), "a failed run must not write a table"
    assert not manifest.exists(), "a failed run must not write a manifest"


# ---------------------------------------------------------------- 2. short month
def test_short_month_fails_without_an_allowance(tmp_path, monkeypatch, capsys):
    """2024-10 is missing c3, which 2024-09 measured. Coverage alone would call the month seen."""
    cache = tmp_path / "cache"
    write_window(cache, "run-a", frame(["2024-09"], ["c1", "c2", "c3"]))
    write_window(cache, "run-b", frame(["2024-10"], ["c1", "c2"]))

    code, out, _ = run(
        tmp_path, monkeypatch, cache, expect_months="2024-09..2024-10", corridors=3
    )

    err = capsys.readouterr().err
    assert code == collect.EXIT_WRONG, f"expected the incomplete month to fail, got exit {code}"
    assert "2024-10 covers 2 of 3 corridors" in err, err
    assert "c3" in err, err
    assert not out.exists()


def test_short_month_passes_as_a_known_gap_when_named(tmp_path, monkeypatch, capsys):
    """The same input, with c3 named in --allow-missing-corridors: exit 3 and a recorded gap."""
    cache = tmp_path / "cache"
    write_window(cache, "run-a", frame(["2024-09"], ["c1", "c2", "c3"]))
    write_window(cache, "run-b", frame(["2024-10"], ["c1", "c2"]))

    code, out, manifest = run(
        tmp_path,
        monkeypatch,
        cache,
        expect_months="2024-09..2024-10",
        corridors=3,
        extra_args=["--allow-missing-corridors", "c3"],
    )

    assert out.exists(), "the accepted gap must still produce the table"
    assert code == collect.EXIT_PARTIAL, f"an accepted gap is partial, not complete: exit {code}"
    payload = json.loads(manifest.read_text(encoding="utf-8"))
    assert payload["known_gaps"] == {"2024-10": ["c3"]}, payload["known_gaps"]
    assert payload["complete"] is False
    assert payload["months_complete"] is True, "the month is present; only corridors are short"
    assert payload["rows"] == 5


# ---------------------------------------------------------------- 3. unexpected gap
def test_unexpected_corridor_gap_fails_even_when_another_is_allowed(tmp_path, monkeypatch, capsys):
    """Allowing c4 must not license c3's absence."""
    cache = tmp_path / "cache"
    write_window(cache, "run-a", frame(["2024-09"], ["c1", "c2", "c3", "c4"]))
    write_window(cache, "run-b", frame(["2024-10"], ["c1", "c2"]))

    code, out, _ = run(
        tmp_path,
        monkeypatch,
        cache,
        expect_months="2024-09..2024-10",
        corridors=4,
        extra_args=["--allow-missing-corridors", "c4"],
    )

    err = capsys.readouterr().err
    assert code == collect.EXIT_WRONG, f"an unnamed gap must fail, got exit {code}"
    assert "c3" in err, err
    assert not out.exists()


# ---------------------------------------------------------------- 4. partial months
def test_missing_months_fail_and_write_nothing_by_default(tmp_path, monkeypatch, capsys):
    cache = tmp_path / "cache"
    write_window(cache, "run-a", frame(["2024-09"], ["c1", "c2"]))

    code, out, manifest = run(
        tmp_path, monkeypatch, cache, expect_months="2024-09..2024-10", corridors=2
    )

    err = capsys.readouterr().err
    assert code == collect.EXIT_WRONG, f"a missing month must fail by default, got exit {code}"
    assert "missing 1 of 2 months" in err, err
    assert "2024-10" in err, err
    assert not out.exists(), "no table may be written when --allow-partial is absent"
    assert not manifest.exists()


def test_allow_partial_writes_and_exits_three(tmp_path, monkeypatch):
    cache = tmp_path / "cache"
    write_window(cache, "run-a", frame(["2024-09"], ["c1", "c2"]))

    code, out, manifest = run(
        tmp_path,
        monkeypatch,
        cache,
        expect_months="2024-09..2024-10",
        corridors=2,
        extra_args=["--allow-partial"],
    )

    assert code == collect.EXIT_PARTIAL, f"--allow-partial is exit 3, got {code}"
    assert out.exists()
    payload = json.loads(manifest.read_text(encoding="utf-8"))
    assert payload["months_complete"] is False
    assert payload["months_missing"] == ["2024-10"]
    assert payload["complete"] is False
    assert payload["months_covered"] == ["2024-09"]


# ---------------------------------------------------------------- 5. clean input
def test_clean_input_exits_zero(tmp_path, monkeypatch, capsys):
    """Two disjoint, complete windows covering the whole expected range.

    The correct answer here is exit 0 (EXIT_COMPLETE), not 3: every expected month is present and
    every month covers the expected corridor count, so nothing is partial.
    """
    cache = tmp_path / "cache"
    write_window(cache, "run-a", frame(["2024-09"], ["c1", "c2", "c3"]))
    write_window(cache, "run-b", frame(["2024-10"], ["c1", "c2", "c3"]))

    code, out, manifest = run(
        tmp_path, monkeypatch, cache, expect_months="2024-09..2024-10", corridors=3
    )

    assert code == collect.EXIT_COMPLETE, f"a complete table is exit 0, got {code}"
    payload = json.loads(manifest.read_text(encoding="utf-8"))
    assert payload["complete"] is True
    assert payload["months_complete"] is True
    assert payload["months_missing"] == []
    assert payload["known_gaps"] == {}
    assert payload["rows"] == 6
    assert payload["corridors"] == 3
    assert payload["duplicate_keys"] == 0
    assert payload["month_values_normalised"] == 0
    assert len(payload["output_sha256"]) == 64
    assert out.stat().st_size > 0
    # provenance: one source entry per window, each naming its run and its months
    assert [s["run_id"] for s in payload["sources"]] == ["run-a", "run-b"]


def test_no_artifacts_is_a_failure(tmp_path, monkeypatch, capsys):
    """An empty cache is exit 1, not a clean empty table."""
    code, out, _ = run(
        tmp_path, monkeypatch, tmp_path / "empty", expect_months="2024-09..2024-09", corridors=1
    )
    assert code == collect.EXIT_WRONG
    assert "no artifacts" in capsys.readouterr().err
    assert not out.exists()


def test_month_spelling_inside_one_window_is_counted_in_the_manifest(tmp_path, monkeypatch):
    """The normalisation count is provenance, and must actually move when a value needed stripping."""
    cache = tmp_path / "cache"
    write_window(cache, "run-a", frame(["2024-09", "2024-10 "], ["c1"]))

    code, out, manifest = run(
        tmp_path, monkeypatch, cache, expect_months="2024-09..2024-10", corridors=1
    )

    assert code == collect.EXIT_COMPLETE, code
    payload = json.loads(manifest.read_text(encoding="utf-8"))
    assert payload["month_values_normalised"] == 1, payload["month_values_normalised"]
    assert out.exists()


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(pytest.main([__file__, "-q"]))
