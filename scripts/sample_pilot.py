"""Phase 3 pilot: sample imagery for one state and measure what it really costs.

Usage:
    python scripts/sample_pilot.py                      # biggest-labelled state, 3 months
    python scripts/sample_pilot.py --state Kano --months 6
    python scripts/sample_pilot.py --resolution 10 --max-tiles 4

Reads:  data/interim/corridors.csv, data/interim/corridor_paths.json.gz
Writes: data/interim/pilot_samples.parquet
        docs/pilot-report.md

Every byte figure comes from the local counting proxy, not from arithmetic on a spec. The point of
this script is to be wrong in public if the estimate was wrong — which, on the first run, it was:
20 m did not cost 92 KB per tile, it cost 857 KB (findings F16).
"""

from __future__ import annotations

import argparse
import gzip
import json
import sys
import time
from collections import defaultdict
from pathlib import Path

import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from roadsense import config, netcount, sampler, tiles  # noqa: E402

CORRIDORS = config.DATA_INTERIM / "corridors.csv"
PATHS = config.DATA_INTERIM / "corridor_paths.json.gz"
OUT = config.DATA_INTERIM / "pilot_samples.parquet"
REPORT = config.DOCS / "pilot-report.md"


def load_paths() -> dict[str, list[list[list[float]]]]:
    with gzip.open(PATHS, "rt", encoding="utf-8") as handle:
        return json.load(handle)


def corridors_in_state(corridors: pd.DataFrame, state: str) -> list[str]:
    """Corridors whose primary state matches, plus any that merely cross it."""
    mask = (corridors["primary_state"] == state) | corridors["states"].fillna("").str.contains(
        rf"(?:^|\|){state}(?:\||$)", regex=True
    )
    return corridors.loc[mask, "name"].tolist()


def tile_index(
    paths_by_name: dict[str, list[list[list[float]]]], names: list[str]
) -> dict[tuple[int, int], list[tuple[str, list[list[float]]]]]:
    """Map each 8 km tile to the corridor paths that touch it.

    Built once so a tile read is followed by cheap local rasterisation rather than a re-fetch.
    """
    index: dict[tuple[int, int], list[tuple[str, list[list[float]]]]] = defaultdict(list)
    for name in names:
        for path in paths_by_name.get(name, []):
            tile_hits = tiles.corridor_tiles([path])
            for tile in tile_hits:
                index[tile].append((name, path))
    return dict(index)


def months_for(items: list[sampler.Item]) -> list[str]:
    return sorted({item.month for item in items})


def pick_month_items(
    items: list[sampler.Item], month: str, tile: tuple[int, int]
) -> sampler.Item | None:
    item_x, item_y = tiles.item_id(tile[0] * tiles.TILE_M, tile[1] * tiles.TILE_M)
    for candidate in items:
        if candidate.month == month and candidate.item_xy == (item_x, item_y):
            return candidate
    return None


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--state", default=None, help="state to pilot; default is the best-labelled")
    parser.add_argument("--months", type=int, default=3, help="most recent N months to sample")
    parser.add_argument("--resolution", type=int, default=sampler.ANALYSIS_M)
    parser.add_argument("--max-tiles", type=int, default=6, help="cap tiles to keep the pilot small")
    parser.add_argument("--no-proxy", action="store_true", help="skip byte counting (faster)")
    args = parser.parse_args()

    if not CORRIDORS.exists() or not PATHS.exists():
        print(f"missing {CORRIDORS} or {PATHS}; run scripts/build_geometry.py first", file=sys.stderr)
        return 1

    corridors = pd.read_csv(CORRIDORS)
    paths_by_name = load_paths()

    state = args.state
    if state is None:
        labelled = corridors[corridors["label_events"] > 0]
        state = labelled["primary_state"].value_counts().index[0]
    names = corridors_in_state(corridors, state)
    index = tile_index(paths_by_name, names)

    tiles_ordered = sorted(index, key=lambda t: -len(index[t]))[: args.max_tiles]
    print(f"[pilot] state={state}  corridors={len(names)}  tiles available={len(index)}  "
          f"sampling={len(tiles_ordered)}  resolution={args.resolution} m")

    # One STAC search for the whole state, then pick months from what came back.
    bounds = [tiles.tile_bounds(tx, ty) for tx, ty in tiles_ordered]
    minx = min(b[0] for b in bounds)
    miny = min(b[1] for b in bounds)
    maxx = max(b[2] for b in bounds)
    maxy = max(b[3] for b in bounds)
    lon0, lat0 = tiles.to_wgs(minx, miny)
    lon1, lat1 = tiles.to_wgs(maxx, maxy)
    bbox = (min(lon0, lon1), min(lat0, lat1), max(lon0, lon1), max(lat0, lat1))

    items = sampler.search(bbox, limit=250)
    all_months = months_for(items)
    chosen = all_months[-args.months :]
    print(f"[pilot] items={len(items)}  months available={len(all_months)} "
          f"({all_months[0]}..{all_months[-1]})  sampling={chosen}")

    proxy = None if args.no_proxy else netcount.CountingProxy().start()
    rows: list[dict] = []
    started = time.time()
    bytes_total = 0
    requests_total = 0
    skipped = 0
    failed = 0

    try:
        for tile in tiles_ordered:
            tx, ty = tile
            for month in chosen:
                item = pick_month_items(items, month, tile)
                if item is None:
                    skipped += 1
                    continue
                if proxy is not None:
                    item = sampler.Item(
                        item.item_id,
                        item.month,
                        {band: proxy.rewire(url) for band, url in item.assets.items()},
                        item.transform,
                        item.shape,
                    )
                    proxy.tally.reset()

                try:
                    bands = {
                        band: sampler.read_tile(item, band, tx, ty, resolution=args.resolution)
                        for band in sampler.BANDS
                    }
                except Exception as exc:  # noqa: BLE001 - a missing COG must not kill the run
                    # Seen in the wild: STAC advertises a recent month whose COGs are not yet
                    # readable. Recording the failure is the honest option; retrying later is
                    # the job of the backfill, not the pilot.
                    failed += 1
                    print(f"  skip ({tx},{ty}) {month}: {type(exc).__name__}")
                    continue

                if proxy is not None:
                    bytes_total += proxy.tally.bytes_out
                    requests_total += proxy.tally.requests

                # A tile serves every corridor crossing it: read once, mask per corridor.
                per_corridor: dict[str, list[list[float]]] = defaultdict(list)
                for name, path in index[tile]:
                    per_corridor[name].append(path)

                for name, path_list in per_corridor.items():
                    inner, ring = sampler.rings(
                        path_list, tx, ty, resolution=args.resolution
                    )
                    if not inner.any():
                        continue
                    values = sampler.indices(
                        bands["B04"], bands["B08"], bands["B11"], inner
                    )
                    verge = sampler.indices(bands["B04"], bands["B08"], bands["B11"], ring)
                    rows.append(
                        {
                            "corridor_name": name,
                            "tile_x": tx,
                            "tile_y": ty,
                            "month": month,
                            "resolution_m": args.resolution,
                            "item_id": item.item_id,
                            **values,
                            "ndvi_verge": verge["ndvi_mean"],
                            "ndbi_verge": verge["ndbi_mean"],
                            "ring_pixels_valid": verge["pixels_valid"],
                            "ndvi_contrast": sampler.contrast(values, verge, "ndvi_mean"),
                            "ndbi_contrast": sampler.contrast(values, verge, "ndbi_mean"),
                        }
                    )

            print(f"  tile ({tx},{ty}): rows so far {len(rows)}  bytes {bytes_total / 1e6:.1f} MB")
    finally:
        if proxy is not None:
            proxy.stop()

    elapsed = time.time() - started
    frame = pd.DataFrame(rows)
    OUT.parent.mkdir(parents=True, exist_ok=True)
    frame.to_parquet(OUT, index=False)

    tile_months = len(tiles_ordered) * len(chosen) - skipped - failed
    per_tile_month = bytes_total / tile_months if tile_months else 0.0
    national = 2_016 * 24 * per_tile_month  # 2,016 measured national tiles (findings O2)

    print("\n[pilot] measured")
    print(f"  {'tile-months sampled':30s} {tile_months}")
    print(f"  {'tile-months failed':30s} {failed}")
    print(f"  {'rows written':30s} {len(frame):,}")
    print(f"  {'elapsed':30s} {elapsed / 60:.1f} min")
    print(f"  {'bytes downloaded':30s} {bytes_total / 1e6:.1f} MB")
    print(f"  {'http requests':30s} {requests_total:,}")
    print(f"  {'bytes per tile-month':30s} {per_tile_month / 1e3:.0f} KB")
    print(f"  {'secs per tile-month':30s} {elapsed / max(tile_months, 1):.1f}")
    print(f"  {'national 24-month projection':30s} {national / 1e9:.1f} GB")
    print(f"  {'serial runtime projection':30s} {2_016 * 24 * elapsed / max(tile_months, 1) / 3600:.0f} h")

    if not frame.empty:
        print("\n  road band vs verge band by corridor:")
        summary = (
            frame.groupby("corridor_name")
            .agg(
                months=("month", "nunique"),
                road=("ndvi_mean", "mean"),
                verge=("ndvi_verge", "mean"),
                contrast=("ndvi_contrast", "mean"),
            )
            .sort_values("contrast")
        )
        for name, row in summary.head(10).iterrows():
            print(
                f"    {name[:38]:38s} n={row.months:2.0f}  road={row.road:6.3f}  "
                f"verge={row.verge:6.3f}  contrast={row.contrast:+.3f}"
            )

    REPORT.write_text(
        "# Phase 3 pilot report\n\n"
        f"Generated {time.strftime('%Y-%m-%d %H:%M')} by `scripts/sample_pilot.py`.\n\n"
        f"- State: **{state}**\n- Resolution: **{args.resolution} m**\n"
        f"- Tiles sampled: {len(tiles_ordered)} ({len(index)} available in state)\n"
        f"- Months: {', '.join(chosen)}\n"
        f"- Tile-months sampled: {tile_months}\n"
        f"- Rows: {len(frame):,}\n\n"
        "| Metric | Measured |\n|---|---:|\n"
        f"| Bytes downloaded | {bytes_total / 1e6:.1f} MB |\n"
        f"| HTTP requests | {requests_total:,} |\n"
        f"| Bytes per tile-month | {per_tile_month / 1e3:.0f} KB |\n"
        f"| Seconds per tile-month | {elapsed / max(tile_months, 1):.1f} |\n"
        f"| National 24-month projection | {national / 1e9:.1f} GB |\n"
        f"| Serial runtime projection | {2_016 * 24 * elapsed / max(tile_months, 1) / 3600:.0f} h |\n\n"
        "Byte figures come from a counting HTTP proxy in front of the S3 endpoint, so they are\n"
        "measured response bodies rather than an estimate multiplied by a guess.\n",
        encoding="utf-8",
    )
    print(f"\n[pilot] wrote {OUT.relative_to(config.ROOT)} and {REPORT.relative_to(config.ROOT)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
