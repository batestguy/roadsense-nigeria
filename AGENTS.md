# Project knowledge

RoadSense Nigeria — scores Nigeria's federal road **corridors** for degradation and allocates a
fixed maintenance budget across them. The unit is the corridor (869 of them), not the segment:
Gate G0 showed the label join cannot support segment-level work (findings F11–F12).

**Read these before doing anything:**

| File | Why |
|---|---|
| `docs/handoff.md` | **Start here.** Current state, runtime expectations, credentials, decisions already made, traps. |
| `preflight-spec.md` | Agreed plan, thresholds and decisions. Supersedes the original proposal where they conflict. |
| `docs/findings.md` | Every measured fact. Do not re-derive these; do re-verify if a source misbehaves. |
| `docs/phases.md` | Current phase, what is done, what is blocked. |
| `#FermaCloud Engineering.txt` | The original proposal. Background only — several of its claims are disproven. |

`knowledge.md` is the short version for quick orientation.

## Quickstart

```bash
python -m pip install -e ".[dev]"           # pandas, numpy, pyarrow, duckdb, pytest, ruff
python -m pytest tests -q                   # 40 tests, no network
python -m ruff check src tests scripts

python scripts/run_gate0.py                 # Gate G0: ~65 MB download, then matching
python scripts/build_corridors.py           # -> data/interim/corridors.csv (869 rows)
python scripts/build_geometry.py            # -> data/interim/corridors.geojson
python scripts/publish_dataset.py           # -> dist/dataset/*.parquet + dataset card
python scripts/check_warehouse.py           # DuckDB views + headline counts

# Imagery (needs .[geo])
python scripts/count_tiles.py               # 2,016 tiles, no download
python scripts/sample_pilot.py              # one-state pilot, measures real bytes
python scripts/ablate_resolution.py         # 10 m vs 40 m -> docs/resolution-ablation.md
python scripts/backfill.py --shard 1/96 --dry-run
```

National backfill: `gh workflow run backfill.yml -f resolution=10 -f shards=96`. Expect **12–20 h
wall clock and ~89 GB streamed**, not stored. 48 shards risks the 6 h job limit; 96 is the default.

Optional extras, by phase: `.[geo]` (rasterio, shapely, pyproj), `.[model]`
(scikit-survival, lifelines, mlflow), `.[optimise]` (pulp), `.[platform]` (feast, dagster).

## Architecture

- `src/roadsense/` — importable package. `textmatch`, `states`, `geometry` are pure logic and
  fully tested; `grid3`, `ocds`, `gate0`, `hf` do I/O; `corridors` builds the modelling unit;
  `warehouse` opens DuckDB views over the parquet.
- `scripts/` — thin CLI entry points that wire the package together.
- `data/` — gitignored. Raw downloads in `data/raw`, derived tables in `data/interim`.
- `dist/dataset/` — gitignored build output that gets uploaded to Hugging Face.
- `docs/` — findings, phases, and the generated gate report.

Data flow:

```
OCDS bundle -> maintenance events -> road phrase + state
            -> GRID3 names        -> confidence-banded matches -> 181 high
GRID3 segments -> corridors (869) -> geometry (GeoJSON) -> parquet -> HF Datasets -> DuckDB views
```

## Conventions

- Keep `textmatch` and `states` dependency-free and unit-tested. They encode the label-quality
  logic, and silently degrading them changes every downstream number.
- Any claim about a data source goes in `docs/findings.md` with its measurement date.
- Never commit data. It lives in Hugging Face Datasets (see `preflight-spec.md`).
- **Do not weaken the Gate G0 thresholds.** They were committed to before the test ran. The gate
  failed at 181 and the response was to re-scope to corridors, not to lower the bar.
- The read path for published data must stay anonymous and dependency-free (`hf.fetch`). Only
  publishing may require `HF_TOKEN`.
- Regenerate `docs/label-matching-report.md`; never hand-edit it. Same for the dataset card, which
  `scripts/publish_dataset.py` writes.

## Things to avoid

- Assuming Copernicus CDSE can serve bulk imagery on the free tier — it cannot (findings F1).
- Treating a procurement record as evidence of physical road failure. It is evidence of spending.
- Using `names IS NOT NULL` on GRID3: 113,004 segments have an empty string and will be counted.
- Requesting GRID3 geometry without `outSR=4326`: it returns Web Mercator metres.
- Touching `float('nan')` truthiness — a NaN passes `if value:` and breaks every guard.
- Expecting Cloudflare R2 to work without a card — it requires a payment method even on the free
  tier (findings F5). Hugging Face Datasets is the tested alternative.
- Reading `label_events > 0` as "the road failed". It means money was allocated.
