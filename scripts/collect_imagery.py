"""Collect the per-window imagery artifacts into one table, with the checks that make it usable.

The national backfill runs in two-month windows. Each window is a separate workflow run whose
`merge` job uploads a single artifact named `imagery-r10`. Nothing concatenated them until now, so
fourteen months of measured imagery lived only in GitHub's artifact store.

Download the windows first (one directory per run id):

    gh run download <run-id> -n imagery-r10 -D data/features/windows/<run-id>

Then:

    python scripts/collect_imagery.py                      # full run: all 22 months required
    python scripts/collect_imagery.py --allow-partial      # while windows are still arriving

Exit codes: 0 complete, 1 the data is wrong, 3 partial (missing months) but written.

Writes `data/features/imagery_r10.parquet` plus a manifest recording which run produced which
months. The manifest is the provenance: a row in the table is traceable to a workflow run and an
artifact expiry date.

Three failures this guards against, each of which a real review found and a test reproduced:

1. The same physical month arriving twice under two string spellings. Windows are produced weeks
   apart, so `2025-01` and `2025-01 ` are both possible; a string-keyed duplicate check sees two
   different months and reports a clean table. Month values are therefore stripped before every
   check from a collection window onwards, and the count of corrected values is recorded.
2. A month present but incomplete. Coverage alone only proves a month was seen, not that all 850
   corridors were measured in it.
3. Schema drift between windows. Columns are compared across windows, not just against a list.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import sys
from datetime import UTC, datetime
from pathlib import Path

import pandas as pd

KEY = ["corridor_id", "tile_x", "tile_y", "month"]
REQUIRED = [
    "corridor_id",
    "corridor_name",
    "tile_x",
    "tile_y",
    "month",
    "resolution_m",
    "item_id",
    "pixels_core",
    "pixels_ring",
    "ndvi_core",
    "ndvi_ring",
    "ndvi_contrast",
    "ndbi_core",
    "ndbi_ring",
    "ndbi_contrast",
]
EXIT_COMPLETE, EXIT_WRONG, EXIT_PARTIAL = 0, 1, 3


def month_range(spec: str) -> list[str]:
    """'2024-09..2026-06' -> every month in it, inclusive."""
    start, end = spec.split("..")
    return [p.strftime("%Y-%m") for p in pd.period_range(start, end, freq="M")]


def sha256(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as fh:
        for chunk in iter(lambda: fh.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def fail(msg: str) -> int:
    print(f"FAIL: {msg}", file=sys.stderr)
    return EXIT_WRONG


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--cache", default="data/features/windows", help="dir holding <run-id>/imagery_r10.parquet")
    ap.add_argument("--out", default="data/features/imagery_r10.parquet")
    ap.add_argument("--manifest", default="data/features/imagery_r10.manifest.json")
    ap.add_argument("--expect-months", default="2024-09..2026-06")
    ap.add_argument("--expect-corridors", type=int, default=850)
    ap.add_argument("--allow-missing-corridors", default="",
                    help="comma-separated corridor_ids whose absence is a known, accepted gap; "
                         "any other shortfall still fails")
    ap.add_argument("--allow-partial", action="store_true")
    args = ap.parse_args()

    cache = Path(args.cache)
    files = sorted(cache.glob("*/imagery_r10.parquet"))
    if not files:
        print(f"no artifacts under {cache}/*/imagery_r10.parquet", file=sys.stderr)
        return EXIT_WRONG

    expect = month_range(args.expect_months)
    frames, sources = [], []
    reference: dict[str, str] | None = None
    normalised_total = 0

    for f in files:
        run_id = f.parent.name
        df = pd.read_parquet(f)

        missing = [c for c in REQUIRED if c not in df.columns]
        if missing:
            return fail(f"{run_id}: missing columns {missing}")

        # 3. schema drift across windows, not just against the required list
        signature = {c: str(df[c].dtype) for c in sorted(df.columns)}
        if reference is None:
            reference = signature
        elif signature != reference:
            diff = {c: (reference.get(c), signature.get(c))
                    for c in set(reference) | set(signature)
                    if reference.get(c) != signature.get(c)}
            return fail(f"{run_id}: schema differs from the first window: {diff}")

        # 1. one physical month, two spellings
        raw_month = df["month"].astype(str)
        df["month"] = raw_month.str.strip()
        normalised = int((raw_month != df["month"]).sum())
        if normalised:
            print(f"{run_id}: WARNING {normalised} month values needed whitespace stripping")
        normalised_total += normalised

        res = sorted(df["resolution_m"].unique().tolist())
        if res != [10]:
            return fail(f"{run_id}: resolution_m is {res}, expected [10]")

        dup = int(df.duplicated(subset=KEY).sum())
        if dup:
            return fail(f"{run_id}: {dup} duplicate keys inside the window")

        months = sorted(df["month"].unique())
        print(f"{run_id}: {len(df):>6} rows  months {months[0]}..{months[-1]}  corridors {df['corridor_id'].nunique()}")
        frames.append(df)
        sources.append({"run_id": run_id, "rows": len(df), "months": months,
                        "months_normalised": normalised})

    all_df = pd.concat(frames, ignore_index=True)

    dup = int(all_df.duplicated(subset=KEY).sum())
    if dup:
        return fail(f"{dup} duplicate keys ACROSS windows — the windows overlap")
    print(f"no duplicate (corridor, tile, month) keys across {len(sources)} windows")

    # 2. a month that exists but is not complete
    all_corridors = set(all_df["corridor_id"].unique())
    per_month = all_df.groupby("month")["corridor_id"].nunique()
    allow = {c.strip() for c in args.allow_missing_corridors.split(",") if c.strip()}
    known_gaps: dict[str, list[str]] = {}
    for m, n in per_month.items():
        if int(n) == args.expect_corridors:
            continue
        present = set(all_df.loc[all_df["month"] == m, "corridor_id"].unique())
        missing_here = sorted(all_corridors - present)
        if not missing_here or not set(missing_here).issubset(allow):
            return fail(f"{m} covers {int(n)} of {args.expect_corridors} corridors; "
                        f"missing {missing_here[:5]} — not covered by --allow-missing-corridors")
        known_gaps[m] = missing_here
        print(f"KNOWN GAP {m}: {len(missing_here)} corridor(s) absent, explicitly accepted "
              f"{missing_here}")
    if not known_gaps:
        print(f"every month covers {args.expect_corridors} corridors")

    covered = sorted(per_month.index.tolist())
    missing_months = [m for m in expect if m not in covered]
    extra_months = [m for m in covered if m not in expect]
    if extra_months:
        return fail(f"unexpected months outside the expected window: {extra_months}")
    if missing_months:
        msg = f"missing {len(missing_months)} of {len(expect)} months: {', '.join(missing_months)}"
        if not args.allow_partial:
            return fail(msg)
        print(f"PARTIAL: {msg}")

    out = Path(args.out)
    out.parent.mkdir(parents=True, exist_ok=True)
    all_df.to_parquet(out, index=False)

    manifest = {
        "generated_at": datetime.now(UTC).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "artifact": "imagery-r10",
        "resolution_m": 10,
        "expected_months": args.expect_months,
        "expected_corridors_per_month": args.expect_corridors,
        "months_covered": covered,
        "months_missing": missing_months,
        "months_complete": not missing_months,
        "complete": (not missing_months) and (not known_gaps),
        "rows": len(all_df),
        "corridors": int(all_df["corridor_id"].nunique()),
        "duplicate_keys": dup,
        "month_values_normalised": normalised_total,
        "known_gaps": known_gaps,
        "sources": sources,
        "output": str(out),
        "output_sha256": sha256(out),
    }
    Path(args.manifest).write_text(json.dumps(manifest, indent=2), encoding="utf-8")

    print(f"\nwrote {out}  rows={len(all_df)}  corridors={all_df['corridor_id'].nunique()}  "
          f"months={len(covered)}/{len(expect)}")
    print(f"manifest {args.manifest}")
    if missing_months or known_gaps:
        print("this table is PARTIAL; do not present it as the finished dataset", file=sys.stderr)
        return EXIT_PARTIAL
    return EXIT_COMPLETE


if __name__ == "__main__":
    raise SystemExit(main())
