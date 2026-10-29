"""O3: does 40 m rank corridors the same way as 10 m?

Usage:
    python scripts/ablate_resolution.py [--state Lagos] [--tiles 3] [--months 3]

Reads:  data/interim/corridors.csv, data/interim/corridor_paths.json.gz
Writes: data/interim/ablation.parquet, docs/resolution-ablation.md

Why this matters: 40 m costs 0.41× what 10 m costs (findings F16), and the national backfill is
budgeted on that saving. But a saving is only free if the cheaper resolution preserves the ranking
the model actually consumes. This script measures that rather than assuming it.

Two correlations are reported, because they answer different questions:

* **Level** — do the two resolutions agree on which corridors are greener today? This is what a
  cross-sectional index needs.
* **Change** — do they agree on which corridors got greener or browner between months? This is what
  a degradation signal needs, and it is the harder test: a resolution can rank levels correctly
  while washing out the month-to-month differences that carry the signal.
"""

from __future__ import annotations

import argparse
import gzip
import json
import sys
from collections import defaultdict
from pathlib import Path

import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from roadsense import config, sampler, tiles  # noqa: E402

CORRIDORS = config.DATA_INTERIM / "corridors.csv"
PATHS = config.DATA_INTERIM / "corridor_paths.json.gz"
OUT = config.DATA_INTERIM / "ablation.parquet"
REPORT = config.DOCS / "resolution-ablation.md"

RESOLUTIONS = (10, 40)


def spearman(a: pd.Series, b: pd.Series) -> float:
    """Rank correlation without pulling in scipy: Spearman is Pearson on ranks."""
    if len(a) < 3:
        return float("nan")
    return float(a.rank().corr(b.rank()))


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--state", default="Lagos")
    parser.add_argument("--tiles", type=int, default=3)
    parser.add_argument("--months", type=int, default=3)
    parser.add_argument(
        "--reuse",
        action="store_true",
        help="rebuild the report from data/interim/ablation.parquet instead of re-sampling",
    )
    args = parser.parse_args()

    if not CORRIDORS.exists() or not PATHS.exists():
        print("run scripts/build_geometry.py first", file=sys.stderr)
        return 1

    corridors = pd.read_csv(CORRIDORS)
    with gzip.open(PATHS, "rt", encoding="utf-8") as handle:
        paths_by_name = json.load(handle)

    names = corridors.loc[
        (corridors["primary_state"] == args.state)
        | corridors["states"].fillna("").str.contains(rf"(?:^|\|){args.state}(?:\||$)", regex=True),
        "name",
    ].tolist()

    index: dict[tuple[int, int], list[tuple[str, list[list[float]]]]] = defaultdict(list)
    for name in names:
        for path in paths_by_name.get(name, []):
            for tile in tiles.corridor_tiles([path]):
                index[tile].append((name, path))

    chosen_tiles = sorted(index, key=lambda t: -len(index[t]))[: args.tiles]
    bounds = [tiles.tile_bounds(tx, ty) for tx, ty in chosen_tiles]
    corners = [tiles.to_wgs(b[0], b[1]) for b in bounds] + [tiles.to_wgs(b[2], b[3]) for b in bounds]
    bbox = (
        min(c[0] for c in corners),
        min(c[1] for c in corners),
        max(c[0] for c in corners),
        max(c[1] for c in corners),
    )

    items = sampler.search(bbox, limit=250)
    months = sorted({item.month for item in items})[-args.months :]
    print(f"[ablation] state={args.state} tiles={len(chosen_tiles)} months={months}")

    lookup = {(item.item_xy, item.month): item for item in items}
    rows: list[dict] = []

    if args.reuse and OUT.exists():
        frame = pd.read_parquet(OUT)
        print(f"[ablation] reusing {len(frame):,} sampled rows from {OUT.name}")
        chosen_tiles = sorted(set(zip(frame['tile_x'], frame['tile_y'], strict=True)))
        months = sorted(frame["month"].unique())

    for tile in [] if (args.reuse and OUT.exists()) else chosen_tiles:
        tx, ty = tile
        item_xy = tiles.item_id(tx * tiles.TILE_M, ty * tiles.TILE_M)
        per_corridor: dict[str, list[list[float]]] = defaultdict(list)
        for name, path in index[tile]:
            per_corridor[name].append(path)

        for month in months:
            item = lookup.get((item_xy, month))
            if item is None:
                continue
            for resolution in RESOLUTIONS:
                try:
                    bands = {
                        band: sampler.read_tile(item, band, tx, ty, resolution=resolution)
                        for band in sampler.BANDS
                    }
                except Exception as exc:  # noqa: BLE001 - a missing COG is not fatal here
                    print(f"  skip {resolution}m ({tx},{ty}) {month}: {type(exc).__name__}")
                    continue

                for name, path_list in per_corridor.items():
                    core, ring = sampler.rings(path_list, tx, ty, resolution=resolution)
                    if not core.any():
                        continue
                    values = sampler.indices(bands["B04"], bands["B08"], bands["B11"], core)
                    verge = sampler.indices(bands["B04"], bands["B08"], bands["B11"], ring)
                    rows.append(
                        {
                            "corridor_name": name,
                            "tile_x": tx,
                            "tile_y": ty,
                            "month": month,
                            "resolution_m": resolution,
                            **{k: values[k] for k in ("ndvi_mean", "ndbi_mean", "pixels_valid")},
                            "ndvi_verge": verge["ndvi_mean"],
                            "ndvi_contrast": sampler.contrast(values, verge, "ndvi_mean"),
                        }
                    )
        print(f"  tile ({tx},{ty}) done, rows={len(rows)}")

    if not (args.reuse and OUT.exists()):
        frame = pd.DataFrame(rows)
        OUT.parent.mkdir(parents=True, exist_ok=True)
        frame.to_parquet(OUT, index=False)

    def paired(column: str) -> pd.DataFrame:
        wide = frame.pivot_table(
            index=["corridor_name", "month"], columns="resolution_m", values=column
        ).dropna()
        wide.columns = [f"{column}_{int(c)}m" for c in wide.columns]
        return wide

    level_wide = paired("ndvi_mean")
    level_rho = spearman(level_wide["ndvi_mean_10m"], level_wide["ndvi_mean_40m"])

    delta = level_wide.groupby(level="corridor_name").diff().dropna()
    change_rho = (
        spearman(delta["ndvi_mean_10m"], delta["ndvi_mean_40m"])
        if len(delta) >= 3
        else float("nan")
    )

    # The contrast feature is the one that carries condition, so it is tested separately.
    contrast_wide = paired("ndvi_contrast")
    contrast_rho = (
        spearman(contrast_wide["ndvi_contrast_10m"], contrast_wide["ndvi_contrast_40m"])
        if len(contrast_wide) >= 3
        else float("nan")
    )

    mean_abs_diff = float((level_wide["ndvi_mean_10m"] - level_wide["ndvi_mean_40m"]).abs().mean())
    bias = float((level_wide["ndvi_mean_40m"] - level_wide["ndvi_mean_10m"]).mean())
    contrast_sign_agree = float(
        (contrast_wide["ndvi_contrast_10m"] > 0).eq(contrast_wide["ndvi_contrast_40m"] > 0).mean()
    )

    print("\n[ablation] measured")
    print(f"  {'pairs compared':30s} {len(level_wide)}")
    print(f"  {'level rank correlation':30s} {level_rho:.3f}")
    print(f"  {'change rank correlation':30s} {change_rho:.3f}")
    print(f"  {'contrast rank correlation':30s} {contrast_rho:.3f}")
    print(f"  {'contrast sign agreement':30s} {contrast_sign_agree:.1%}")
    print(f"  {'mean absolute NDVI gap':30s} {mean_abs_diff:.4f}")
    print(f"  {'40 m minus 10 m bias':30s} {bias:+.4f}")

    level_ok = level_rho >= 0.8 and (pd.isna(change_rho) or change_rho >= 0.6)
    contrast_ok = (not pd.isna(contrast_rho) and contrast_rho >= 0.6) and contrast_sign_agree >= 0.8
    verdict = (
        "40 m is acceptable for the level index **and** the contrast feature — use 40 m."
        if level_ok and contrast_ok
        else (
            "40 m preserves the level index but not the contrast feature — "
            "run the condition signal at 10 m."
            if level_ok
            else "40 m does not preserve the ranking — pay for 10 m."
        )
    )

    REPORT.write_text(
        "# Resolution ablation (O3)\n\n"
        f"Generated by `scripts/ablate_resolution.py` for **{args.state}**.\n\n"
        f"- Tiles: {len(chosen_tiles)}; months: {', '.join(months)}\n"
        f"- Corridor-months compared: {len(level_wide)}\n\n"
        "| Metric | Value | Threshold |\n|---|---:|---:|\n"
        f"| Level rank correlation (Spearman) | {level_rho:.3f} | ≥ 0.80 |\n"
        f"| Change rank correlation (Spearman) | {change_rho:.3f} | ≥ 0.60 |\n"
        f"| Contrast rank correlation (Spearman) | {contrast_rho:.3f} | ≥ 0.60 |\n"
        f"| Contrast sign agreement | {contrast_sign_agree:.1%} | ≥ 80% |\n"
        f"| Mean absolute NDVI gap | {mean_abs_diff:.4f} | — |\n"
        f"| Bias (40 m − 10 m) | {bias:+.4f} | — |\n\n"
        f"**Verdict: {verdict}**\n\n"
        "Three correlations are reported because they answer different questions. *Level* is what a\n"
        "cross-sectional index needs. *Change* is what a degradation signal needs. *Contrast* is what\n"
        "separates a maintained corridor from a failing one, and it is the test a coarse resolution\n"
        "is most likely to fail: a 40 m pixel containing a road is a road-plus-verge mixture, so the\n"
        "difference between carriageway and verge can vanish or invert even when levels still rank.\n",
        encoding="utf-8",
    )
    print(f"\n[ablation] {verdict}")
    print(f"[ablation] wrote {OUT.relative_to(config.ROOT)} and {REPORT.relative_to(config.ROOT)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
