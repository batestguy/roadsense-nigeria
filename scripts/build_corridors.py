"""Build the corridor table from cached segments and Gate G0 matches.

Usage:
    python scripts/build_corridors.py

Reads:  data/interim/segments.csv, data/interim/label_matches.csv
Writes: data/interim/corridors.csv
"""

from __future__ import annotations

import sys
from pathlib import Path

import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from roadsense import config, corridors  # noqa: E402

SEGMENTS = config.DATA_INTERIM / "segments.csv"
MATCHES = config.DATA_INTERIM / "label_matches.csv"
OUT = config.DATA_INTERIM / "corridors.csv"


def main() -> int:
    if not SEGMENTS.exists():
        print(f"missing {SEGMENTS}; run scripts/run_gate0.py first", file=sys.stderr)
        return 1

    segments = pd.read_csv(SEGMENTS)
    table = corridors.build_corridors(segments)

    if MATCHES.exists():
        table = corridors.attach_labels(table, pd.read_csv(MATCHES))
    else:
        print("note: no label_matches.csv, corridor table will show zero labels")

    OUT.parent.mkdir(parents=True, exist_ok=True)
    table.to_csv(OUT, index=False)

    summary = corridors.summarise(table)
    print("[corridors] built")
    for key, value in summary.items():
        print(f"  {key:34s} {value}")

    top = table.nlargest(8, "label_events")[["name", "primary_state", "length_km", "label_events"]]
    print("\n  most-labelled corridors:")
    for row in top.itertuples(index=False):
        print(f"    {row.name[:46]:46s} {row.primary_state:12s} {row.length_km:8.1f} km  "
              f"events={row.label_events}")

    print(f"\n[corridors] wrote {OUT.relative_to(config.ROOT)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
