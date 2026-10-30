"""National imagery backfill: sharded, resumable, and honest about what it costs.

Usage:
    python scripts/backfill.py --shard 1/48 --resolution 10
    python scripts/backfill.py --limit-tiles 4 --months 1        # smoke test
    python scripts/backfill.py --shard 3/48 --dry-run            # plan only, no downloads

Reads:  data/interim/corridors.csv, data/interim/corridor_paths.json.gz
Writes: data/features/imagery_r{res}_shard{nn}.parquet
        data/features/backfill_state_r{res}_shard{nn}.json

Why sharded: the measured rate is ~10-30 s per tile-month (findings F17), and there are 2,016 tiles
× 24 months = 48,384 tile-months. That is 130-400 hours serial, well beyond a single CI job limit,
so the work is split across shards that never share a tile.

Why resumable: a 70 GB national run at 10 m will be interrupted — a runner dies, a month is
re-released, someone cancels. Each shard appends to its own parquet and skips any (tile, month) it
already holds, so re-running a shard resumes rather than restarts.

Shard assignment is a strided slice over the sorted tile list. That is deterministic across
processes without a lock or a coordinator, and it keeps a shard's tiles geographically scattered
rather than clustered on one 96 km item — which matters because a single slow item would otherwise
stall one shard while the others finish.
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

from roadsense import config, sampler, tiles  # noqa: E402
from roadsense.corridors import alias_map  # noqa: E402

CORRIDORS = config.DATA_INTERIM / "corridors.csv"
PATHS = config.DATA_INTERIM / "corridor_paths.json.gz"
FEATURES = config.ROOT / "data" / "features"

COLUMNS = [
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


def parse_shard(value: str) -> tuple[int, int]:
    try:
        index, total = value.split("/")
        index_i, total_i = int(index), int(total)
    except ValueError as exc:
        raise argparse.ArgumentTypeError("shard must look like 1/48") from exc
    if not 1 <= index_i <= total_i:
        raise argparse.ArgumentTypeError(f"shard index must be between 1 and {total_i}")
    return index_i, total_i


def load_index() -> tuple[dict[str, str], dict[tuple[int, int], list[tuple[str, str, list]]]]:
    """Tile -> the corridors crossing it, plus ``corridor_id -> canonical name``.

    Names resolve through the alias map: a variant spelling still has geometry in the cache but
    no row of its own in the corridor table (findings F20). Resolving through the alias keeps
    its paths, and grouping on the canonical name means one corridor crossing a tile under two
    spellings yields one row rather than two — the duplicate that failed the merge gate.
    """
    with gzip.open(PATHS, "rt", encoding="utf-8") as handle:
        paths_by_name = json.load(handle)
    table = pd.read_csv(CORRIDORS)
    id_by_name = alias_map(table)
    name_by_id = dict(zip(table["corridor_id"], table["name"], strict=True))

    index: dict[tuple[int, int], list[tuple[str, str, list[list[float]]]]] = defaultdict(list)
    for name, paths in paths_by_name.items():
        corridor_id = id_by_name.get(name)
        if corridor_id is None:
            continue
        canonical = name_by_id[corridor_id]
        for path in paths:
            for tile in tiles.corridor_tiles([path]):
                index[tile].append((corridor_id, canonical, path))
    return name_by_id, dict(index)


def months_in(start: str, end: str) -> list[str]:
    """Every ``YYYY-MM`` between two months, inclusive."""
    start_year, start_month = (int(part) for part in start.split("-"))
    end_year, end_month = (int(part) for part in end.split("-"))
    months: list[str] = []
    year, month = start_year, start_month
    while (year, month) <= (end_year, end_month):
        months.append(f"{year:04d}-{month:02d}")
        month += 1
        if month > 12:
            year, month = year + 1, 1
    return months


def done_keys(path: Path) -> set[tuple[int, int, str]]:
    if not path.exists():
        return set()
    frame = pd.read_parquet(path, columns=["tile_x", "tile_y", "month"])
    return set(zip(frame["tile_x"], frame["tile_y"], frame["month"], strict=True))


def flush(rows: list[dict], path: Path) -> None:
    """Append a batch, keeping one parquet file per shard.

    Parquet has no append, so the existing file is read back and rewritten. That is fine at these
    sizes (48,384 rows total nationally, a few MB) and avoids needing a database for a batch job.
    """
    if not rows:
        return
    frame = pd.DataFrame(rows, columns=COLUMNS)
    if path.exists():
        frame = pd.concat([pd.read_parquet(path), frame], ignore_index=True)
    path.parent.mkdir(parents=True, exist_ok=True)
    frame.to_parquet(path, index=False)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--shard", type=parse_shard, default=(1, 1), help="i/N, 1-indexed")
    parser.add_argument("--resolution", type=int, default=10, help="10 m for the condition signal")
    parser.add_argument("--start", default="2024-09", help="first month, YYYY-MM")
    parser.add_argument("--end", default="2026-06", help="last month, YYYY-MM")
    parser.add_argument("--limit-tiles", type=int, default=None, help="smoke test: cap the tiles")
    parser.add_argument("--batch", type=int, default=40, help="tile-months per write")
    parser.add_argument("--dry-run", action="store_true", help="print the plan, download nothing")
    args = parser.parse_args()

    if not CORRIDORS.exists() or not PATHS.exists():
        print("run scripts/build_geometry.py first", file=sys.stderr)
        return 1

    _, index = load_index()
    all_tiles = sorted(index)
    shard_index, shard_total = args.shard
    my_tiles = all_tiles[(shard_index - 1) :: shard_total]
    if args.limit_tiles:
        my_tiles = my_tiles[: args.limit_tiles]
    months = months_in(args.start, args.end)

    stem = f"imagery_r{args.resolution}_shard{shard_index:02d}of{shard_total:02d}"
    out = FEATURES / f"{stem}.parquet"
    state_path = FEATURES / f"{stem}.json"

    already = done_keys(out)
    print(
        f"[backfill] shard {shard_index}/{shard_total}  tiles={len(my_tiles)}  months={len(months)}  "
        f"pending={len(my_tiles) * len(months) - len(already):,}  already={len(already):,}"
    )
    if args.dry_run:
        estimated = (len(my_tiles) * len(months) - len(already)) * 646e3
        print(f"[backfill] dry run: ~{estimated / 1e9:.1f} GB to stream for this shard")
        return 0

    item_cache: dict[str, dict[tuple[int, int], sampler.Item]] = {}
    rows: list[dict] = []
    written = 0
    missing = 0
    started = time.time()

    try:
        for tile in my_tiles:
            tx, ty = tile
            item_xy = tiles.item_id(tx * tiles.TILE_M, ty * tiles.TILE_M)
            for month in months:
                if (tx, ty, month) in already:
                    continue

                if month not in item_cache:
                    # One STAC search per month over the national bbox: ~97 items, one page.
                    found = sampler.search(
                        config.NIGERIA_BBOX,
                        start=f"{month}-01",
                        end=f"{month}-28",
                        limit=250,
                    )
                    item_cache[month] = {item.item_xy: item for item in found}

                item = item_cache[month].get(item_xy)
                if item is None:
                    missing += 1
                    continue

                try:
                    bands = {
                        band: sampler.read_tile(item, band, tx, ty, resolution=args.resolution)
                        for band in sampler.BANDS
                    }
                except Exception:  # noqa: BLE001 - unavailable month, not a fatal error
                    missing += 1
                    continue

                per_corridor: dict[tuple[str, str], list[list[float]]] = defaultdict(list)
                for corridor_id, name, path in index[tile]:
                    per_corridor[(corridor_id, name)].append(path)

                for (corridor_id, name), path_list in per_corridor.items():
                    core, ring = sampler.rings(path_list, tx, ty, resolution=args.resolution)
                    if not core.any():
                        continue
                    road = sampler.indices(bands["B04"], bands["B08"], bands["B11"], core)
                    verge = sampler.indices(bands["B04"], bands["B08"], bands["B11"], ring)
                    rows.append(
                        {
                            "corridor_id": corridor_id,
                            "corridor_name": name,
                            "tile_x": tx,
                            "tile_y": ty,
                            "month": month,
                            "resolution_m": args.resolution,
                            "item_id": item.item_id,
                            "pixels_core": road["pixels_valid"],
                            "pixels_ring": verge["pixels_valid"],
                            "ndvi_core": road["ndvi_mean"],
                            "ndvi_ring": verge["ndvi_mean"],
                            "ndvi_contrast": sampler.contrast(road, verge, "ndvi_mean"),
                            "ndbi_core": road["ndbi_mean"],
                            "ndbi_ring": verge["ndbi_mean"],
                            "ndbi_contrast": sampler.contrast(road, verge, "ndbi_mean"),
                        }
                    )

                written += 1
                if len(rows) >= args.batch:
                    flush(rows, out)
                    rows = []
                    elapsed = time.time() - started
                    rate = elapsed / max(written, 1)
                    print(
                        f"  {written:,} tile-months  {rate:.1f}s each  "
                        f"elapsed {elapsed / 60:.0f} min",
                        flush=True,
                    )
    finally:
        flush(rows, out)
        state_path.parent.mkdir(parents=True, exist_ok=True)
        state_path.write_text(
            json.dumps(
                {
                    "shard": f"{shard_index}/{shard_total}",
                    "resolution_m": args.resolution,
                    "tiles": len(my_tiles),
                    "months": months,
                    "tile_months_written": written,
                    "missing": missing,
                    "seconds": round(time.time() - started, 1),
                    "rows": int(len(pd.read_parquet(out))) if out.exists() else 0,
                },
                indent=2,
            ),
            encoding="utf-8",
        )

    print(f"\n[backfill] shard {shard_index}/{shard_total} done")
    print(f"  tile-months written this run  {written:,}")
    print(f"  tile-months unavailable       {missing:,}")
    print(f"  rows in {out.name:24s} {len(pd.read_parquet(out)) if out.exists() else 0:,}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
