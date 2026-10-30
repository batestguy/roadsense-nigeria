# Handoff — read this first

Last updated **2026-10-29**. Companion to `docs/findings.md` (what was measured),
`docs/phases.md` (where the build is) and `preflight-spec.md` (what was agreed).

If you are picking this up cold: read this page, then `docs/findings.md`. Everything else is
detail you can look up when you need it.

---

## Where the project stands

A corridor-level road intelligence pipeline for Nigeria's federal network, built on a zero-cost
cloud stack. **Phases 0–2 complete; Phase 3 built and smoke-tested, national run not yet done.**

| Layer | State |
|---|---|
| Labelling (Gate G0) | Done. Failed its threshold; the project re-scoped to corridors |
| Corridor table | Done — 850 corridors, 18,419 km, geometry for all of them |
| Dataset publishing | Code complete, **never uploaded** (needs `HF_TOKEN`) |
| Imagery sampler | Done and measured — the cost model is measured, not estimated |
| Backfill runner | Done, smoke-tested on a GitHub runner end to end |
| Weather ingest | **Not started** |
| Model / index / dashboard | **Not started** |

Two things are unusual about this repo and worth internalising before reading code:

1. **The unit is a corridor, not a segment.** Gate G0 showed the label join cannot support
   segment-level work. `corridor_id` is the join key everywhere.
2. **The notes are the product of the first two phases.** Several claims in the original proposal
   were wrong, and `docs/findings.md` records the corrections with measurements. Do not
   re-litigate them from the proposal; challenge the findings instead, with data.

---

## How long does the national backfill take?

The question everyone asks, answered from measured rates rather than hope:

| Quantity | Value | Source |
|---|---:|---|
| Distinct 8 km tiles containing highway | 2,016 | F18 |
| Months per tile | 22 (default window 2024-09 … 2026-06) | script default |
| Tile-months of work | 44,352 | 2,016 × 22 |
| Seconds per tile-month at 10 m | **1–4** | **F21, measured on a runner** |
| **Serial compute** | **12–49 h** | |
| Bytes streamed at 10 m | **~70 GB** | F16/F17 |
| Per shard at 96 shards | 8–31 min | 462 tile-months each |
| **Wall clock** | **~1–3 h** | ~20 concurrent jobs, ~5 waves |

**~1–3 hours wall clock, roughly 70 GB streamed, £0/$0** — measured, not projected, for two months,
and extrapolated from there (F21). The earlier 12–20 h figure came from the 40 m workstation pilot,
where every 8 km read cost nine overview requests instead of one base tile. Nothing is stored: the
table that survives is a few MB.

96 shards remains the default. The 6 h job limit no longer binds, but a cancelled job still loses
whatever shard it was in, so smaller units are cheaper to lose.

---

## Backfill progress (as of 2026-10-30, 23:56 UTC)

The national run is being done in 2-month windows of 96 shards, ~18 min each (F21). Windows are
disjoint, so each produces its own `imagery-r10` artifact; they concatenate on
`(corridor_id, tile_x, tile_y, month)` at the end. Two windows are merged and a third is in
flight:

| Window | State | Run |
|---|---|---|
| 2024-09 … 2024-10 | ✅ merged, 6,292 rows | 41140244419 |
| 2024-11 … 2024-12 | ✅ merged, 6,292 rows | 41142676535 |
| 2025-01 … 2025-02 | ✅ merged | 41144644682 |
| 2025-03 … 2025-04 | ▶ dispatched 23:46 | 41146408420 |
| 2025-05 … 2026-06 | ⏳ 7 windows not dispatched | — |

**Check the real state first** — this table is a snapshot, not a live view:

```bash
gh run list --workflow=backfill.yml --limit 12
```

**Resume one window at a time.** The workflow keeps only one *pending* run per concurrency group, so
dispatching a batch silently cancels all but one. Adjust the list to skip windows already merged:

```bash
for w in "2025-05 2025-06" "2025-07 2025-08" "2025-09 2025-10" "2025-11 2025-12" \
         "2026-01 2026-02" "2026-03 2026-04" "2026-05 2026-06"; do
  set -- $w
  gh workflow run backfill.yml -f resolution=10 -f shards=96 -f start=$1 -f end=$2
  sleep 1200   # the run must finish before the next dispatch, or it is cancelled
 done
```

Notes for whoever picks this up cold:

- Completed windows keep their artifacts for **90 days**. Nothing is lost if a session is cut off;
  the loss is only of the ~18 min of the shard that was running.
- The local driver used on 2026-10-30 is `data/run_sessions.sh` — gitignored, machine-local, and
  without memory: restarting it replays windows from the top of its list. Use the loop above instead
  unless you re-read that file first.
- A per-window merge only proves the key is unique and the output is non-empty. The end-to-end
  checks are the 22-artifact concatenation and the seasonal comparison in F22.

---

## Running things

```bash
# Install. [geo] is needed for anything touching imagery.
python -m pip install -e ".[dev,geo]"

# Offline: 64 tests, no network
python -m pytest tests -q
python -m ruff check src tests scripts

# Rebuild the corridor tables (network, ~65 MB, a few minutes)
python scripts/run_gate0.py
python scripts/build_corridors.py
python scripts/build_geometry.py

# Coverage and cost, no imagery downloaded
python scripts/count_tiles.py

# Measure a pilot for real (a few MB)
python scripts/sample_pilot.py --months 3 --max-tiles 5

# Resolution comparison; writes docs/resolution-ablation.md
python scripts/ablate_resolution.py --tiles 3 --months 3

# Backfill: plan, smoke, or run
python scripts/backfill.py --shard 1/96 --dry-run
python scripts/backfill.py --shard 1/96 --limit-tiles 3 --start 2026-06 --end 2026-06
```

To run the national job from GitHub:

```bash
gh workflow run backfill.yml -f resolution=10 -f start=2024-09 -f end=2026-06 -f shards=96
```

---

## Credentials

Exactly one thing in this project needs a credential, and it is not the data.

| Need | Status |
|---|---|
| `HF_TOKEN` repo secret | **not set** — required only by `.github/workflows/pipeline.yml` |
| Hugging Face account | does not exist yet |
| Anything else | none — GRID3, DE Africa S3, OCDS, GitHub Pages are all anonymous |

Imagery reads, corpus downloads and the backfill need **no** credential. If a task appears to need
one, something is being done the wrong way.

---

## What is genuinely blocked

| Blocked | On what |
|---|---|
| Any modelling | The national backfill — there are no features yet |
| Dataset publication | `HF_TOKEN` |
| Index validation | The backfill, plus a decision on the control group |

Nothing else is blocked. Everything in Phases 0–3 ran on live data.

---

## Decisions already made — do not re-open without new evidence

| Decision | Why | Evidence |
|---|---|---|
| Corridors, not segments | GRID3 names 869 corridors, 850 once variant spellings are merged; 113,004 segments are unnamed | F11/F12/F20 |
| 10 m imagery, not 40 m | 40 m flips the contrast sign on 20.6% of corridor-months | F19 |
| Road-versus-verge contrast, not centreline NDVI | A centreline pixel is asphalt; NDVI ≈ 0 regardless of condition | F17/F19 |
| Hugging Face, not Cloudflare R2 | R2 requires a payment method even on the free tier | F5 |
| OpenTofu over Terraform | Terraform's licence; also the only infrastructure here is the repo itself | spec §10 |
| 48 GB figure abandoned | F2's "20 m is 10× cheaper" compared tiles of different ground area | F16 |

---

## Traps that have already cost time

1. **`names IS NOT NULL` is wrong on GRID3** — 113,004 segments carry an empty string. Use
   `names <> ''`.
2. **GRID3 geometry needs `outSR=4326`**, otherwise it arrives in Web Mercator metres and every
   point-in-polygon test silently fails.
3. **`float('nan')` is truthy** — NaN passes `if value:` and defeats null guards.
4. **Never read a partial window at the first overview level.** GDAL streams the entire 172 MB file.
   Read the whole 8 km tile.
5. **A `HEAD` with `Content-Length: 0` makes GDAL abandon range requests** and download whole files.
6. **Do not dilate a mask and keep calling it the same thing.** A 50 m dilation at 40 m is one
   pixel; that mistake produced a confident, entirely fake finding about Lagos.
7. **Reading the published dataset is anonymous; publishing is not.** Keep that asymmetry.

---

## Next, in order

1. **Run the national backfill** — `-f shards=96 -f resolution=10`. Expect 12–20 h.
2. **Weather ingest** — Open-Meteo per 1° cell, ~150 calls, non-commercial licence. Independent of
   the backfill; can be built before it finishes.
3. **Corridor condition index** from `ndvi_contrast` / `ndbi_contrast` over time.
4. **Validation with a control group.** Compare the 66 labelled corridors against *unlabelled
   corridors of the same class and length band*. Without the control, a good AUC only proves that
   busy federal corridors are busy.
5. Then, and only then, modelling, optimisation and the map.

Deliberately deferred: dbt and Feast. The feature table is a few hundred thousand rows that pandas
and DuckDB already handle; adding those layers now would be infrastructure without a user.

---

## Deliverables still missing

Data dictionary, model card, architecture diagram, Quarto report, cost analysis, demo video,
MapLibre site, Dagster demo DAG, Grafana dashboard. None exist. The README, findings register,
pilot report, resolution ablation and this page do.
