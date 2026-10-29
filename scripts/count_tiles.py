"""Count the 8 km imagery tiles that actually contain federal highway.

Usage:
    python scripts/count_tiles.py

Answers open question O2 — "how many distinct 8 km tiles actually contain highway?" — without
downloading a single byte of imagery. Reads the cached corridor paths from
`scripts/build_geometry.py`, so run that first.

The distinction that matters: a rectangle around Nigeria is ~2,300 tiles, but most of them are
empty savannah and desert. Only tiles the corridors actually touch need fetching, and the ratio
between those two numbers is what determines the national backfill cost.
"""

from __future__ import annotations

import gzip
import json
import sys
from collections import Counter
from pathlib import Path

import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from roadsense import config, tiles  # noqa: E402

CACHE = config.DATA_INTERIM / "corridor_paths.json.gz"
CORRIDORS = config.DATA_INTERIM / "corridors.csv"

#: Measured bytes for one 8 km tile in one band, by analysis resolution (findings F16).
#: The plan's figure was 92 KB at 20 m, which counted one 256 px overview tile rather than the
#: nine needed to cover 8 km — an under-estimate of nearly 9×.
BYTES_PER_TILE = {10: 933_888, 20: 857_016, 40: 387_622, 80: 193_730}

#: Bands read per tile: B04, B08, B11. The third is only needed for NDBI.
BANDS = 3


def main() -> int:
    if not CACHE.exists() or not CORRIDORS.exists():
        print(f"missing {CACHE} or {CORRIDORS}; run scripts/build_geometry.py first", file=sys.stderr)
        return 1

    with gzip.open(CACHE, "rt", encoding="utf-8") as handle:
        paths_by_name = json.load(handle)
    corridors = pd.read_csv(CORRIDORS).set_index("name")

    per_corridor: dict[str, set[tuple[int, int]]] = {}
    for name, paths in paths_by_name.items():
        found = tiles.corridor_tiles(paths)
        if found:
            per_corridor[name] = found

    all_tiles: set[tuple[int, int]] = set().union(*per_corridor.values())
    items = {tiles.item_id(tx * tiles.TILE_M, ty * tiles.TILE_M) for tx, ty in all_tiles}

    print("[tiles] coverage")
    print(f"  {'corridors with geometry':30s} {len(per_corridor):,}")
    print(f"  {'distinct 8 km tiles':30s} {len(all_tiles):,}")
    print(f"  {'distinct 96 km items':30s} {len(items):,}")
    print(f"  {'tiles per corridor (median)':30s} "
          f"{pd.Series([len(v) for v in per_corridor.values()]).median():.0f}")
    print(f"  {'tiles per corridor (max)':30s} "
          f"{max(len(v) for v in per_corridor.values()):,}")

    # Grid-cell occupancy, to show how sparse the network is inside its own bounding box.
    xs = [tx for tx, _ in all_tiles]
    ys = [ty for _, ty in all_tiles]
    span = (max(xs) - min(xs) + 1) * (max(ys) - min(ys) + 1)
    print(f"\n  bounding box of touched tiles: {(max(xs) - min(xs) + 1)} x "
          f"{(max(ys) - min(ys) + 1)} = {span:,} tiles")
    print(f"  occupancy: {len(all_tiles) / span:.1%} of that box contains highway")

    by_state: Counter[str] = Counter()
    for name, found in per_corridor.items():
        state = corridors.loc[name, "primary_state"] if name in corridors.index else "?"
        by_state[str(state)] += len(found)
    print("\n  tiles by primary state (top 10 — a shared tile is counted once per state):")
    for state, count in by_state.most_common(10):
        print(f"    {state:24s} {count:5,}")

    # Cost arithmetic from measured bytes, not from the plan's estimate.
    #
    # These are UPPER BOUNDS: each band is charged its cold single-band cost, but in practice the
    # COG header is read once and shared across the three bands, so the pilot measured 646 KB per
    # tile-month at 40 m against the 1.16 MB this arithmetic implies (findings F17). Quote the
    # pilot figure when a single number is needed.
    print("\n  national backfill at 3 bands, by resolution (upper bound):")
    for resolution, per_band in sorted(BYTES_PER_TILE.items()):
        total_24 = len(all_tiles) * 24 * BANDS * per_band / 1e9
        refresh = len(all_tiles) * BANDS * per_band / 1e6
        print(
            f"    {resolution:>3} m   24 months {total_24:7.1f} GB   "
            f"monthly refresh {refresh:6.1f} MB"
        )
    print("\n  measured end-to-end (pilot, 40 m, 3 bands): 646 KB per tile-month")
    print(f"  -> {len(all_tiles) * 24 * 646e3 / 1e9:.1f} GB for 24 months")

    print(f"\n[count] {len(all_tiles):,} tiles -> closes O2 (estimate was 6,000)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
