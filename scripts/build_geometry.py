"""Build corridor geometry for the map.

Usage:
    python scripts/build_geometry.py [--tolerance 0.0001] [--force]

Reads:  data/interim/corridors.csv
Caches: data/interim/corridor_paths.json.gz   (merged paths, so refetching is optional)
Writes: data/interim/corridors.geojson

The cache exists because the fetch is ~54,000 features over 27 paged requests. Tuning the
simplification tolerance should not mean hitting GRID3 again every time.
"""

from __future__ import annotations

import argparse
import gzip
import json
import sys
from pathlib import Path

import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from roadsense import config, geometry  # noqa: E402
from roadsense.corridors import merge_paths_by_corridor  # noqa: E402

CORRIDORS = config.DATA_INTERIM / "corridors.csv"
CACHE = config.DATA_INTERIM / "corridor_paths.json.gz"
OUT = config.DATA_INTERIM / "corridors.geojson"


def load_paths(force: bool) -> dict[str, list[list[list[float]]]]:
    if CACHE.exists() and not force:
        with gzip.open(CACHE, "rt", encoding="utf-8") as handle:
            return json.load(handle)

    print("[geometry] fetching named highway geometry ...")
    paths = geometry.collect_corridor_paths()
    CACHE.parent.mkdir(parents=True, exist_ok=True)
    with gzip.open(CACHE, "wt", encoding="utf-8") as handle:
        json.dump(paths, handle)
    return paths


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--tolerance",
        type=float,
        default=0.0001,
        help="RDP tolerance in degrees (~11 m at 9 deg N). 0 disables simplification.",
    )
    parser.add_argument("--force", action="store_true", help="refetch instead of using cache")
    args = parser.parse_args()

    if not CORRIDORS.exists():
        print(f"missing {CORRIDORS}; run scripts/build_corridors.py first", file=sys.stderr)
        return 1

    table = pd.read_csv(CORRIDORS)
    paths_by_name = load_paths(args.force)

    raw_vertices = sum(len(path) for group in paths_by_name.values() for path in group)
    print(
        f"[geometry] cache holds {len(paths_by_name):,} names, "
        f"{sum(len(g) for g in paths_by_name.values()):,} paths, {raw_vertices:,} vertices"
    )

    # Variant spellings of one corridor are separate names in the cache but one row in the
    # table, so fold them together before the join (findings F20).
    paths = merge_paths_by_corridor(table, paths_by_name)
    matched_vertices = sum(len(path) for group in paths.values() for path in group)
    print(
        f"[geometry] {len(paths):,} corridors matched, {matched_vertices:,} vertices "
        f"({'complete' if matched_vertices == raw_vertices else 'partial'})"
    )

    fc = geometry.build_feature_collection(table, paths, tolerance=args.tolerance)
    geometry.write_feature_collection(fc, OUT)

    size_mb = OUT.stat().st_size / 1e6
    covered = len(fc["features"])
    print("\n[geometry] built")
    print(f"  {'corridors in table':28s} {len(table):,}")
    print(f"  {'corridors with geometry':28s} {covered:,}")
    print(f"  {'corridors missing geometry':28s} {len(fc['missing']):,}")
    print(f"  {'vertices after simplify':28s} {fc['total_vertices']:,}")
    print(f"  {'vertices before simplify':28s} {raw_vertices:,}")
    print(f"  {'tolerance (deg)':28s} {args.tolerance}")
    print(f"  {'output size':28s} {size_mb:.2f} MB")

    if fc["missing"]:
        print("\n  first 10 corridors with no geometry:")
        for name in fc["missing"][:10]:
            print(f"    {name[:60]}")

    # A quick sanity check that the map will not show corridors in the wrong hemisphere.
    lons = [f["properties"]["bbox"][0] for f in fc["features"]]
    lats = [f["properties"]["bbox"][1] for f in fc["features"]]
    if lons and lats:
        print(
            f"\n  extent: lon {min(lons):.3f}..{max(lons):.3f}, "
            f"lat {min(lats):.3f}..{max(lats):.3f}  (Nigeria is ~2.7..14.7 E, 4.3..13.9 N)"
        )

    print(f"\n[geometry] wrote {OUT.relative_to(config.ROOT)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
