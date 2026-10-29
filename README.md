# RoadSense Nigeria

A degradation index and maintenance-allocation study for Nigeria's federal highway network, built
entirely from open data at zero recurring cost.

> **Status: re-scoped after Gate G0; Phases 0–2 complete, Phase 3 built and smoke-tested on CI.
> The national imagery run (~89 GB, 12–20 h) has not been executed yet.** Pick up from
> [`docs/handoff.md`](docs/handoff.md).
> The label-matching gate returned **181 high-confidence matches** against a 300 threshold. The
> cause is a data limit rather than a code defect: GRID3 gives names to 869 corridors and leaves
> 113,004 highway segments unnamed, so most procurement records cannot be joined to the network.
> The project therefore models **corridors** rather than segments, leads with a satellite
> degradation index that needs no labels, and uses the 181 interventions as an external validation
> check. Full reasoning in [`docs/label-matching-report.md`](docs/label-matching-report.md) and
> findings F11–F14 in [`docs/findings.md`](docs/findings.md).

## The problem

Nigeria has roughly 36,000 km of federal roads. Maintenance is reactive — repairs follow failure,
and allocation tracks budget cycles more than measured need. There is no public system that says
which corridors are deteriorating fastest, or where a fixed budget buys the most.

## The approach

| Step | What happens | Status |
|---|---|---|
| 1 | Corridor network from GRID3, merged to 869 corridors | ✅ built |
| 2 | Intervention records from Nigeria's open procurement data | ✅ built |
| 3 | Cloud-free monthly Sentinel-2 composites from Digital Earth Africa | 🔄 sampler proven, sharded backfill built, national run pending |
| 4 | Rainfall and soil moisture from Open-Meteo | ⏳ Phase 3 |
| 5 | Degradation index across all 869 corridors (no labels needed) | ⏳ Phase 5 |
| 6 | Budget allocation with a knapsack, and the trade-off reported honestly | ⏳ Phase 6 |

## What this repository contains today

| Path | Contents |
|---|---|
| `src/roadsense/` | Package: matching (`textmatch`, `states`, `gate0`), ingestion (`grid3`, `ocds`), modelling units (`corridors`, `geometry`), imagery (`tiles`, `sampler`, `netcount`), storage (`hf`, `warehouse`) |
| `scripts/run_gate0.py` | Downloads sources, matches labels, writes the gate report |
| `scripts/build_corridors.py` | Builds the 869-corridor modelling table |
| `scripts/build_geometry.py` | Builds corridor geometry as GeoJSON (2.74 MB raw, 0.64 MB gzipped) |
| `scripts/publish_dataset.py` | Packages parquet + dataset card, optionally uploads |
| `scripts/check_warehouse.py` | Verifies the DuckDB views and prints headline counts |
| `scripts/count_tiles.py` | Counts the 8 km imagery tiles that actually contain highway |
| `scripts/sample_pilot.py` | One-state imagery pilot with exact byte accounting |
| `scripts/ablate_resolution.py` | 10 m vs 40 m comparison for the condition signal |
| `scripts/backfill.py` | Sharded, resumable national imagery backfill |
| `tests/` | 64 tests over matching, states, corridors, geometry, imagery, dataset access, warehouse |
| `docs/findings.md` | Every measured finding, with dates, sources and what changed as a result |
| `docs/handoff.md` | **Start here** — state, runtime, credentials, decisions, traps |
| `docs/phases.md` | Build phases, dependencies and current status |
| `docs/pilot-report.md` | Generated imagery pilot measurements |
| `docs/resolution-ablation.md` | Generated 10 m vs 40 m comparison |
| `preflight-spec.md` | Agreed scope, thresholds and decisions |

## Quickstart

```bash
python -m pip install -e ".[dev]"
python -m pytest tests -q                       # 64 tests, no network

python scripts/run_gate0.py                     # ~65 MB of sources, then matching
python scripts/build_corridors.py
python scripts/build_geometry.py                # corridor GeoJSON for the map
python scripts/publish_dataset.py               # parquet + dataset card in dist/dataset
python scripts/check_warehouse.py               # DuckDB counts: 869 corridors, 2,036 events

python scripts/count_tiles.py                   # 2,016 imagery tiles, no download
python scripts/sample_pilot.py                  # measures real bytes for one state
python scripts/ablate_resolution.py             # 10 m vs 40 m, writes docs/resolution-ablation.md
python scripts/backfill.py --shard 1/48 --dry-run   # plan a shard without downloading
```

`publish_dataset.py --upload` pushes to Hugging Face and needs `HF_TOKEN`. Reading the dataset
never does — the published files are public and served over plain HTTPS.

## Data

Derived tables live at [`roadsense-ng/nigeria-roads`](https://huggingface.co/datasets/roadsense-ng/nigeria-roads)
on Hugging Face Datasets: `corridors.parquet`, `events.parquet`, `label_matches.parquet`.

```python
import pandas as pd
BASE = "https://huggingface.co/datasets/roadsense-ng/nigeria-roads/resolve/main"
corridors = pd.read_parquet(f"{BASE}/corridors.parquet")
```

Hugging Face is not a preference: Cloudflare R2 requires a payment method on the account to
enable, even on the free tier, so it would break the project's no-card rule (findings F5).

## Honest limitations

- A procurement record is evidence that **money was spent**, not that a road physically failed. The
  target is intervention need, and that is a proxy.
- GRID3 names only **869 corridors**; 113,004 highway segments have no name at all, so they can
  never be joined to a label textually.
- The procurement source has **no coordinates** and **no 2022 records**. Half of all maintenance
  events (997 of 2,036) fall in 2025, which is also the temporal test year.
- The apparent 2024 procurement spike is **40% new construction and 34% noise** once classified;
  the maintenance series is far flatter than the raw counts suggest (findings F13).
- Traffic volume has no free Nigerian source, so any "value" term must be a labelled proxy.
- Open-Meteo's free tier is **non-commercial use only**.
- Sampling NDVI on a road centreline gives ≈ 0: a 40 m pixel is mostly asphalt. The signal has to
  be a road-versus-verge contrast, which is a Phase 4 design change (findings F17).
- The road-condition signal needs **10 m** imagery (~70 GB, ~281 h serial), not 40 m: at 40 m the
  verge contrast flips sign on one corridor-month in five (findings F19). A coarse landscape index
  would be fine at 40 m, but that is not what the project is for.
- The plan's original imagery cost estimate was off by ~9×; per-tile bytes are now measured, not
  inferred (findings F16).

## Licence

Code: MIT ([`LICENSE`](LICENSE)). Derived data: CC BY-SA 4.0 ([`DATA_LICENSE.md`](DATA_LICENSE.md)),
inherited from GRID3. Attribution requirements are listed there.
