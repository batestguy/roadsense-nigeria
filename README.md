# RoadSense Nigeria

A reproducible, zero-cost measurement of satellite-observed change on Nigeria's 850 federal highway
corridors — and the negative result that came out when that measurement was tested against open
procurement records.

**Status**

- **Built:** a 22-month, 10 m satellite series over all 850 corridors, plus rainfall for the same
  corridor-months.
- **Found:** the pre-specified test of that series against road-spending records **failed**, and the
  point estimate points the opposite way to the hypothesis.
- **Next:** a publication decision on the drafted paper, then the polish pass, which is the work in
  hand.
- **Cost:** $0 in recurring spend.
- **The report:** [batestguy.github.io/roadsense-nigeria/publish](https://batestguy.github.io/roadsense-nigeria/publish/) — five charts, the method, and
  what this does not claim.
- **The data:** [JBZABC/roadsense-nigeria](https://huggingface.co/datasets/JBZABC/roadsense-nigeria) —
  five tables, four manifests, and a card that states the negative result first.
- **The paper:** [10.5281/zenodo.24081356](https://doi.org/10.5281/zenodo.24081356) — a preprint under
  CC BY 4.0; source in [`docs/paper.md`](docs/paper.md).

## The finding

Against a pre-registered bar of AUC ≥ 0.60, the primary test returns **AUC 0.3901**, 95% interval
**0.3196 – 0.4671**. The whole interval sits below the bar, and below 0.50: corridors that received
maintenance money score *less* degraded on this measure than corridors that did not. The secondary
instrument returns **0.4318** (0.3544 – 0.5137) and the raw-level reference returns **0.3133**
(0.2461 – 0.3881). This is a null result with the sign reversed, not a weak signal to be tuned.

The pre-specified decision rule, written before the run, was AUC ≥ 0.60 with the bootstrap lower bound
above 0.50; anything else is reported as a null. The test is in
[`scripts/validate_signal_v2.py`](scripts/validate_signal_v2.py) and its spec was fixed in advance.

### The check that caught the mistake

The first validation score gave every fully covered corridor an identical value, because the anomaly
it averaged is zero by construction for a corridor observed in all its own months. A score that is the
same everywhere cannot detect anything: it ranked data coverage, not condition. A degeneracy gate now
runs **before** any AUC and stops the run if a score has fewer than 50 distinct values, more than 20%
of corridors on its modal value, or a standard deviation near zero. This was caught before the result
was reported, and it is the reason the negative result above can be trusted.

## How it was measured

| Quantity | Value |
|---|---|
| Corridor network | 850 corridors, 18,419 km |
| Measurement period | 22 months, 2024-09 … 2026-06 |
| Satellite readings | 69,212 corridor-tile-month observations, 10 m, three bands |
| Readings per month | 3,146, covering all 850 corridors every month |
| Blank readings | 378 (0.55%) — left blank, never filled or interpolated |
| Collection | 11 independent two-month workflow runs, 96 shards each, ~70 GB streamed by measured byte rates, $0 |
| Weather | 18,700 corridor-months over 82 grid cells, 0 missing days |
| Condition series | 18,700 corridor-months, corridor and month level removed |
| Variance split | month 5.9%, corridor 81.2%, residual 12.8% (month entered first) |
| Validation (primary) | AUC 0.3901, 95% interval 0.3196 – 0.4671, bar 0.60 |
| Validation (secondary) | AUC 0.4318, interval 0.3544 – 0.5137 |
| Reference (raw contrast, confounded) | AUC 0.3133, interval 0.2461 – 0.3881 |

The 378 blanks matter: they are months where the composite had no usable pixel, and they are reported
as blanks rather than imputed. The 0.55% rate is low enough that coverage is not the explanation for
the result.

## Reproduce it

The first two commands need no data download and no credentials.

```bash
python -m pip install -e ".[dev]"
python -m pytest tests -q                       # no network, no credentials

python scripts/count_tiles.py                   # 2,016 imagery tiles, no download
python scripts/run_gate0.py                     # ~65 MB of open sources, then matching
python scripts/build_corridors.py               # -> data/interim/corridors.csv, 850 rows
python scripts/build_geometry.py
python scripts/collect_imagery.py               # merge downloaded per-window artifacts, with coverage checks
python scripts/build_weather.py                 # Open-Meteo archive, no key required
python scripts/build_condition.py               # -> data/interim/condition.parquet
python scripts/validate_signal_v2.py            # pre-specified test -> data/interim/validation_v2.json
```

The imagery behind the series is collected by workflow, not by hand:
`gh workflow run backfill.yml -f resolution=10 -f shards=96`, once per two-month window. Each run
streams its window and stores nothing.

## What this does not claim

- **Movement, not condition.** The measure is a satellite contrast between the carriageway and its
  verge. It observes change in reflectance; it is not a pavement rating or a roughness survey.
- **Reanalysis, not gauges.** Rainfall is a gridded reanalysis product on 1° cells, not station data.
- **An observational comparison with 66 positives.** Corridors that received money are compared with
  those that did not. Nothing here is randomised and nothing here is causal.
- **No accuracy claim.** The only validated quantity is the AUC above, and it is below chance for this
  label.
- **Procurement is spending, not failure.** A maintenance record means money was allocated; it does not
  mean the road physically failed.
- **One licence restriction worth reading.** The reanalysis weather is free for
  **non-commercial** use. The code is MIT and the derived satellite tables follow GRID3's CC BY-SA;
  the weather terms are narrower than the rest, and a commercial deployment would break them. It is
  stated on the dataset card, not buried here.

## Repository map

| Path | Contents |
|---|---|
| `src/roadsense/` | Package: matching (`textmatch`, `states`, `gate0`), ingestion (`grid3`, `ocds`), corridors and geometry, imagery (`tiles`, `sampler`, `netcount`), storage (`hf`, `warehouse`) |
| `scripts/` | Thin CLI entry points, one per pipeline stage |
| `tests/` | Unit tests over matching, states, corridors, geometry, imagery, dataset access, warehouse |
| `docs/` | Findings, phases, handoff, generated gate and pilot reports |
| `preflight-spec.md` | Agreed scope, thresholds and decisions, committed before the tests ran |

## Read further

- **The article:** [`docs/article.md`](docs/article.md) — the same argument in prose, for someone who
  will never clone this repository.
- [`docs/handoff.md`](docs/handoff.md) — current state, runtime, credentials, traps. Start here.
- [`docs/findings.md`](docs/findings.md) — every measured fact, with its date and source.
- [`docs/phases.md`](docs/phases.md) — what is built, what failed, what is next.
- [`docs/label-matching-report.md`](docs/label-matching-report.md) — why the label gate failed and the
  project moved to corridors.

## Licence

Code: MIT ([`LICENSE`](LICENSE)). Derived data: CC BY-SA 4.0 ([`DATA_LICENSE.md`](DATA_LICENSE.md)),
inherited from GRID3. Attribution requirements are listed there.
