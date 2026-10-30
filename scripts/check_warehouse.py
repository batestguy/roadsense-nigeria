"""Verify the DuckDB warehouse view against the built tables.

Usage:
    python scripts/check_warehouse.py [--remote]

Local mode reads `dist/dataset/*.parquet` (run scripts/publish_dataset.py first, without
--upload). Remote mode reads the same files over HTTPS from Hugging Face, which is how a fresh
clone would consume them.
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from roadsense import warehouse  # noqa: E402

#: Corridors the build should produce. This changes when the name grouping changes, not when the
#: data drifts: 850 since case/punctuation variants were merged (findings F20), down from 869 rows.
EXPECTED_CORRIDORS = 850


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--remote", action="store_true", help="read over HTTPS instead of locally")
    args = parser.parse_args()

    con = warehouse.connect(remote=args.remote)
    mode = "remote (HTTPS)" if args.remote else "local parquet"
    print(f"[warehouse] mode: {mode}")

    summary = warehouse.summary(con)
    for key, value in summary.items():
        print(f"  {key:26s} {value:>10,.1f}" if isinstance(value, float) else f"  {key:26s} {value:>10,}")

    # A query that is awkward in pandas and trivial here: labelled corridors never touched since
    # 2024, i.e. the ones where an intervention happened and then stopped.
    stale = con.execute(
        """
        SELECT name, primary_state, length_km, label_events, label_years
        FROM corridors
        WHERE label_events > 0
          AND label_years NOT LIKE '%2025%'
        ORDER BY label_events DESC
        LIMIT 5
        """
    ).fetchall()

    print(f"\n  corridors labelled but silent since 2024: {len(stale)} shown")
    for name, state, km, events, years in stale:
        print(f"    {name[:44]:44s} {state:12s} {km:7.1f} km  {events} events  {years}")

    if summary["corridors"] != EXPECTED_CORRIDORS:
        print(
            f"\n[warehouse] unexpected corridor count: {summary['corridors']} "
            f"(expected {EXPECTED_CORRIDORS})",
            file=sys.stderr,
        )
        return 1

    print("\n[warehouse] ok")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
