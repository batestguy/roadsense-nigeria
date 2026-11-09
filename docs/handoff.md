# Handoff — read this first

Last updated **2026-11-09**. Companion to `docs/findings.md` (what was measured),
`docs/phases.md` (where the build is) and `docs/article.md` (the argument in prose).

If you are picking this up cold: read this page, then `docs/findings.md`.

---

## What this project is now

It measures change on Nigeria's 850 named federal highway corridors from free satellite imagery,
22 months at 10 m, and tests whether that measurement separates corridors that received maintenance
money from comparable ones that did not.

**It does not.** The pre-registered test failed, and the honest output is the measurement, the
pipeline, and the negative result — not a model.

## Where it stands

| Layer | State |
|---|---|
| Corridor network | ✅ 850 corridors, 18,419 km |
| Satellite measurement | ✅ 22 months, 2024-09 … 2026-06, 69,212 readings, every month complete |
| Weather | ✅ monthly 18,700 corridor-months; daily rolling features 18,700 |
| Condition measure | ✅ 18,700 corridor-months, corridor and month effects removed |
| Validation against procurement records | ✅ run, **failed**: AUC 0.3901, bar 0.60 |
| Hazard model | ⛔ **not proceeding** — see below |
| Optimisation, budget allocation | ⛔ depends on the model |
| Public report page | ✅ live |
| Dataset | ✅ published, anonymous download verified |
| Corridor map | ✅ inside the report page |
| Article | ✅ written and published in the repo |
| Paper | ✅ published as a preprint, DOI 10.5281/zenodo.24081356 (CC BY 4.0); source in `docs/paper.md` |

### The three URLs

- **Report:** <https://batestguy.github.io/roadsense-nigeria/publish/>
- **Data:** <https://huggingface.co/datasets/JBZABC/roadsense-nigeria>
- **Source:** <https://github.com/batestguy/roadsense-nigeria>

## The numbers, and what they mean

| Quantity | Value |
|---|---|
| Satellite readings | 69,212 (corridor × tile × month) |
| Corridor-months | 18,700 = 850 × 22 |
| Blank contrast values | 378 (0.55%) — left blank, never filled |
| Corridor-months with no usable reading | 183 across 124 corridors |
| Variance: month / corridor / residual | 5.9% / 81.2% / 12.8% (month entered first) |
| Primary test (pre-registered) | AUC **0.3901**, interval 0.3196–0.4671, bar 0.60 |
| Secondary (trend slope) | 0.4318, interval 0.3544–0.5137 |
| Reference (raw contrast) | 0.3133, interval 0.2461–0.3881 |
| Analysed sample | 644 corridors: 66 labelled, 578 matched unlabelled |

**Read the direction, not just the number.** The whole interval lies below 0.50: corridors with a
procurement record score as *less* degraded than comparable corridors without one. The association
that does exist runs the same way as the raw, uncorrected appearance — which tracks road type and
land cover, not maintenance.

## The mistake worth knowing about

The first validation score was **algebraically degenerate**. It averaged a value that had already
been centred on each corridor's own mean, over the same corridor's months, which is identically zero.
726 of 850 corridors received the same value to fifteen decimal places; the ranking came from which
months were missing (correlation 0.94).

It produced a plausible-looking AUC of 0.5735. It could not have detected anything. A gate now
refuses to compute an AUC before checking that the score varies, and it runs **before** the test.

Do not present that 0.5735 as a result, and do not mention the post-hoc mirror of the corrected test
(0.6099) — it is recorded in the analysis files only so it can be recognised and refused.

## What is genuinely blocked

| Blocked | On what |
|---|---|
| Any hazard model | The validation result. Do not build one on this measure. |
| The reversed hypothesis | New data. Testing the mirror direction on the same numbers is not a test. |
| A journal submission | The paper is now a Zenodo preprint (10.5281/zenodo.24081356, CC BY 4.0). A journal would still cost money: the only in-scope Nigerian Scopus title charges ₦80,000 and is currently closed to submissions. |
| A commercial deployment | The weather reanalysis is **non-commercial only**. The code is MIT; derived tables are CC BY-SA. |

Nothing else is blocked. No credentials are needed to read the data or run the page.

## Decisions already made — do not re-open without new evidence

| Decision | Why | Evidence |
|---|---|---|
| Corridors, not segments | The label join cannot support segments: 113,004 GRID3 segments are unnamed | F11/F12/F20 |
| 10 m imagery, not 40 m | 40 m flips the contrast sign on 20.6% of corridor-months | F19 |
| Road-versus-verge contrast, not centreline NDVI | A centreline pixel is asphalt; NDVI ≈ 0 regardless of condition | F17 |
| Month-first variance split is quoted with its order | The split is order-dependent (82.1/5.1 vs 5.9/81.2) | F22 note |
| No model on the current measure | Two pre-specified instruments, both below the bar | F23 |
| Publish the negative result | A tuned model would not survive the first interview question | this page |

## Traps that have already cost time

1. **`names IS NOT NULL` is wrong on GRID3** — 113,004 segments carry an empty string.
2. **GRID3 geometry needs `outSR=4326`**, or it arrives in Web Mercator metres.
3. **`float('nan')` is truthy** — NaN passes `if value:` and defeats null guards.
4. **Never read a partial window at the first overview level** — GDAL streams the whole 172 MB file.
5. **A `HEAD` with `Content-Length: 0` makes GDAL abandon range requests.**
6. **A path summed over its own window is identically zero.** Centring a value on a corridor's own
   mean and then averaging that value over the same corridor gives zero, not a small number. This is
   the T18 failure and it looked like a result.
7. **A check that cannot fail is not a check.** Two tests in this project were written so that they
   could not possibly fail (an sd ratio under a constant shift; a coverage counter). Both were caught
   after the fact. When writing a guard, ask what input would break it, and run that input.

## How to run it

```bash
python -m pip install -e ".[dev]"
python -m pytest tests -q                 # 91 tests, no network, no credentials
python -m ruff check src tests scripts

python scripts/collect_imagery.py         # merge downloaded per-window artifacts, with coverage gates
python scripts/build_weather.py           # Open-Meteo archive, no key
python scripts/build_weather_daily.py     # rolling 30-day, 7-day max, dry spells
python scripts/build_condition.py         # corpus + month effects removed
python scripts/validate_signal_v2.py      # the pre-registered test
python scripts/build_report.py            # regenerates docs/publish/index.html from the data
python scripts/publish_hf.py              # stages and uploads the dataset
```

The imagery is collected by workflow, one two-month window at a time:
`gh workflow run backfill.yml -f resolution=10 -f shards=96 -f start=YYYY-MM -f end=YYYY-MM`.
Each run streams its window and stores nothing. The windows' artifacts expire 90 days after each run
(the eleven used here were produced 2026-10-30 and 2026-11-09).

## Repository shape

| Path | Contents |
|---|---|
| `src/roadsense/` | `textmatch`, `states`, `gate0` (matching); `grid3`, `ocds` (ingestion); `corridors`, `geometry`; `tiles`, `sampler`, `netcount`; `hf`, `warehouse` |
| `scripts/` | One CLI per pipeline stage, plus `build_report.py` and `publish_hf.py` |
| `tests/` | 91 tests, including the guard tests that are proved to fail when the guard is removed |
| `docs/publish/` | The generated report page and its `facts.json` — never hand-edited |
| `docs/article.md` | The same argument for a reader who will not clone the repo |
| `docs/paper.md` | The formal paper, published as a preprint: 10.5281/zenodo.24081356 |
| `docs/handoff.md` | This page |

Data does not live in git. `data/` is gitignored; the published copy is on Hugging Face.

## What a new session should do first

The user is preparing a polish pass and will bring suggestions. The items already identified:

1. **The map's colour palette.** "Rising contrast" is drawn green, which reads as *better* when rising
   contrast is not a good thing. One palette decision in `scripts/build_report.py`, then re-render and
   re-measure.
2. **README length.** 115 lines; a third of it belongs in `docs/`.
3. **The article's voice.** It is written in the assistant's register, not the owner's. This is the
   one that needs a human, and it matters most for the audience the page is for.
4. **The paper.** Published as a preprint: DOI 10.5281/zenodo.24081356, CC BY 4.0, nine pages, source
   in `docs/paper.md`. The literature review behind it is in `.agent/T26-report.md` and the review in
   `.agent/T27-review.md`.

Before changing anything, run `python scripts/build_report.py` and confirm it reproduces the
committed page byte-for-byte. If it does not, something has drifted and that matters more than polish.
