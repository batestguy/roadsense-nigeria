# preflight-spec.md — RoadSense Nigeria: build specification

Status: agreed, ready to build. Created 2026-10-28.
This document supersedes `#FermaCloud Engineering.txt` wherever they conflict, and records the
decisions taken during the pre-build interview.

Companion documents:
- `#FermaCloud Engineering.txt` — original nine-layer project proposal (source of the ambition).
- `feasibility-assessment.md` — measured feasibility study; every number marked there as measured was
  taken from a live source, not estimated.

---

## 1. What we are building

A public portfolio project that estimates, per Nigerian federal road segment, the probability of
needing a maintenance intervention in the next 12 months, then allocates a fixed budget across
segments to maximise the value those interventions preserve. Everything runs on permanent free tiers,
with no credit card required at any point.

The deliverable that a visitor meets is a MapLibre map of Nigeria with segments shaded by risk, a
click-through to each segment's satellite and weather history, and a budget control that shows how
many segments a given budget covers.

**Honest framing, used consistently everywhere:** the model predicts *where maintenance money is
needed*, not *when a road will physically fail*. This is stated in the README, the model card, and the
dashboard legend. It is not a hedge bolted on at the end — it is the target definition.

---

## 2. Decisions locked in the interview

| Decision | Choice | Consequence |
|---|---|---|
| Purpose | Portfolio / job hunting | Optimise for defensible model + compelling demo + clean repo; not for client delivery |
| Timeline | **6–8 weekends** (extended from 2–3 to fit all layers) | Milestone plan in §6 assumes 8 |
| Role split | Agent writes runnable code, user learns alongside | Every module gets a short "what this does and why" explanation; no unexplained magic |
| Success bar | All four: runs end to end, defensible, compelling, decision-relevant | Explicit acceptance criteria in §8 |
| Geography | **Decided by Gate G0**, not in advance | Build the matcher first; scope follows the labels, not the map |
| Model framing | **Hazard primary, survival secondary** | Discrete-time hazard is the result; Cox PH + RSF appear as a clearly-labelled secondary section |
| Label gate | **Stop and re-scope if < 300 matches** | Committed in advance; §5 defines exactly what "stop" means |
| Stack depth | All six layers real, not decorative | Orchestration, dbt, feature store, experiment tracking, IaC, observability each get real artefacts |
| Orchestration | **GitHub Actions for real runs; one DAG as a demo** | Actions is the production path; Dagster (recommended) or Prefect demonstrated separately |
| Feature store | **Feast, self-hosted** | Apache 2.0, no account, Parquet offline store, local registry |
| Storage | **Hugging Face Datasets** (R2 rejected) | R2 requires a payment method to enable — violates the no-card constraint |
| Repo | **Public from day one** | Free unlimited Actions minutes on standard runners |
| Dashboard | **MapLibre vector map** (not Streamlit) | Static build on **GitHub Pages** |
| Licence | **MIT for code, CC BY-SA 4.0 for derived data** | GRID3 is CC BY-SA 4.0; derived tables inherit share-alike |
| Observability | **Grafana Cloud free tier** | Pipeline metrics and DQC results emitted as metrics |
| Analysis artefacts | **Quarto** for the narrative, notebooks as working files | Quarto is the published artefact; notebooks support it, not replace it |
| Framing tone | **Name FERMA, policy-neutral** | Direct about the 2026 directive; factual, no accusation |
| Budget display | **Percentage of network fundable** | Currency-agnostic; avoids arguing about naira figures |

### Decisions I was asked to make ("choose best")

- **Demo DAG:** Dagster OSS. No account, asset-based lineage is the stronger data-engineering signal,
  and it does not add a vendor to a no-card project. Prefect Hobby remains the documented alternative.
- **IaC:** OpenTofu managing **GitHub repository configuration** via the GitHub provider — branch
  protection, Actions permissions, secrets names, Pages config. This is chosen because it is the only
  infrastructure that actually exists in this design. Provisioning a cloud account to give Terraform
  something to do would be theatre. The spec's original OpenTofu-for-AWS plan is retained as a
  documented alternative only.

---

## 3. Verified facts to build against

All **measured** on 2026-10-28. Do not re-derive these from assumptions; do re-verify if a source
starts behaving differently.

### Road network — GRID3 NGA Roads v1.0
- Endpoint: `services3.arcgis.com/BU6Aadhn6tbBEdyk/arcgis/rest/services/GRID3_NGA_roads/FeatureServer`
- **6,274,965** segments total; anonymous access; CC BY-SA 4.0; `maxRecordCount` 2000 (≈84 paged
  requests per full class pull).
- Fields: `id, country, iso3, source_id, class, speed_estimate, speed_estimate_method, road_surface,
  names, subclass, speed_limits, date, source_acronym, Shape__Length`.
- Class counts: residential 3,837,761 · unclassified 868,542 · track 836,650 · unknown 283,457 ·
  tertiary 136,898 · service 74,103 · **secondary 70,304** · path 62,418 · **primary 56,262** ·
  **trunk 38,074** · footway 6,105 · **motorway 2,362**.
- **Universe = motorway + trunk + primary + secondary = 167,002.**

### Labels — Nigeria OCDS (NOCOPO / BPP, via data.open-contracting.org publication 64)
- 98,866 contracting processes, May 2021 – Oct 2026. 9,862 (10.0%) mention roads.
- FERMA 2,196 processes · Federal Ministry of Works 4,641 · road-related union **3,233**.
- Year split of the 3,233: 2021: 804 · **2022: 0** · 2023: 221 · 2024: 1,288 · 2025: 920 · **2026: 0**.
- **No coordinate field exists.** 2,632 rows (81.4%) name a Nigerian state. 2,974 unique project
  titles of 3,233 rows (only ~223 repeat).
- Amounts: `planning_budget_amount` present for 3,233 (100%); `tender_value_amount` for 688.

### Imagery — Digital Earth Africa Sentinel-2 Rolling Monthly GeoMAD
- STAC: `explorer.digitalearth.africa/stac`, collection `gm_s2_rolling`.
- Data: `deafrica-services.s3.af-south-1.amazonaws.com`, **anonymous**, HTTP 206 range reads, valid COG.
- Item: 9600 × 9600 px @ 10 m (96 km tile), EPSG:6933, monthly 3-month rolling window, 2019–present,
  1-month latency. Bands include B02–B12, B8A, plus EMAD/SMAD/BCMAD/COUNT.
- **Internal tile: 800 × 800 px (8 km). Bytes per internal tile: ~886 KB at full 10 m.** File size
  172 MB per band per tile-month. Overviews at 4800/2400/1200/600/300 px, **~92 KB per tile at 20 m**.
- Measured range-request latency: ~440 ms per 64 KB from this workstation.

### Free tiers (verified against live quota pages)
| Service | Allowance | Our use |
|---|---|---|
| GitHub Actions (public repo) | Unlimited standard-runner minutes | Backfill ~4 h, monthly refresh ~3 min |
| Hugging Face Datasets | Free public hosting, no card | < 500 MB of Parquet |
| Grafana Cloud free | 10k metrics series, 50 GB logs, 14-day retention | A handful of series |
| Open-Meteo Historical | 10k calls/day, **non-commercial only** | ~150 calls/week |
| GitHub Pages | Free static hosting, soft 100 GB/month bandwidth | A few MB of tiles/GeoJSON |
| GRID3 FeatureServer | Anonymous, no quota | 84 requests once |
| DE Africa S3 | Anonymous, no quota | ~40 GB streamed once |

Rejected: **Cloudflare R2** (requires a payment method to enable, confirmed by multiple community
reports — incompatible with the no-card rule). **Copernicus CDSE** free tier is 10k Sentinel Hub
requests + 10k PU/month with the Batch Processing API unavailable — two to three orders of magnitude
short of a per-scene design, so it is not used for the pipeline.

### Toolchain (verified to resolve on this machine, Python 3.14.4 / pandas 3.0.3)
`rasterio 1.5.2` · `geopandas 1.2.0` · `pyproj 3.8.0` · `shapely 2.2.0` · `duckdb 2.0.0` ·
`rioxarray 0.23.0` · `feast 0.67.0` · `dagster 1.13.27` · `mlflow 3.17.2` ·
`scikit-survival 0.28.0` · `lifelines 0.30.3` · PuLP (bundles CBC).

No Python-version blocker. Note `duckdb 2.0.0` is a major release — follow current docs, not 1.x
tutorials.

---

## 4. Architecture

### Real path (what actually runs)

```
GRID3 FeatureServer ──┐
OCDS / NOCOPO ────────┼──► ingest (Actions) ──► Parquet ──► HF Datasets
DE Africa GeoMAD S3 ──┤                                    │
Open-Meteo ───────────┘                                    ▼
                                          DuckDB / dbt transformations
                                                           │
                                                           ▼
                                        Feast feature views (Parquet offline)
                                                           │
                                                           ▼
                                   Discrete-time hazard model (MLflow tracked)
                                                           │
                              ┌────────────────────────────┴──────────┐
                              ▼                                       ▼
                     Knapsack allocator                    Cox PH + RSF (secondary)
                              │
                              ▼
                  risk GeoJSON/PMTiles + metrics ──► GitHub Pages (MapLibre)
                                                  └─► Grafana Cloud (metrics)
```

### Documented-only path (alternatives named in the README, not built)
Prefect Cloud · Kestra · DBOS · Restate · Step Functions · MotherDuck · Databricks · BigQuery ·
Supabase · Turso · dbt Cloud · SQLMesh · Dataform · Hopsworks · SageMaker Feature Store · pycox ·
p-BART · Terraform · AWS CDK · SST · CloudFront.

The README must distinguish clearly between **built** and **documented alternative**. A layer list
where the reader cannot tell which is which is worse than a shorter list.

---

## 5. Gate G0 — the label test

This is the first work item and the only true go/no-go in the project.

**Method**
1. Extract from the 3,233 rows: the road phrase (regex around `road|highway|expressway|bypass|route`),
   the named state (from the 37-name gazetteer), and the intervention type (maintenance / rehabilitation
   / repair vs construction / access road / street light — the latter excluded).
2. Normalise: lowercase, strip punctuation, expand common abbreviations (LGA, SH, BYP), drop
   direction/qualifier tokens.
3. Match against GRID3 `names` within the state's bounding box, then score candidates:
   token overlap (Jaccard), Levenshtein ratio, endpoint proximity if the phrase names two towns
   (`A-B road` pattern), and segment class plausibility.
4. Assign a confidence band: high (≥0.85), medium (0.6–0.85), low (<0.6). Only high-confidence matches
   enter training; medium go to a review file; low are discarded and counted.

**Thresholds, committed in advance**

| High-confidence matches | Action |
|---|---|
| ≥ 800 | Proceed, national scope is defensible |
| 300–800 | Proceed, but scope to the states with adequate coverage; state the coverage gap explicitly |
| < 300 | **Stop.** Write up the finding, do not build the pipeline, re-scope with me before continuing |

**Deliverable:** `docs/label-matching-report.md` with match counts by confidence band, by state, by
year, the code that produced them, and a list of the 50 highest-confidence and 50 lowest-confidence
matches for eyeballing.

**Gate G0 runs in parallel with repo scaffolding**, per the interview — but no imagery sampling, no
modelling, and no dashboard work happens until it reports.

---

## 6. Milestone plan (8 weekends)

Each milestone has an exit criterion. If a milestone slips by more than one weekend, cut scope from
the *end* of the plan, not from the middle.

| # | Weekend | Work | Exit criterion |
|---|---|---|---|
| M1 | 1 | Repo scaffold (empty-but-correct CI, MIT + CC BY-SA licences, README skeleton) ‖ **Gate G0** | Gate G0 report committed with a verdict |
| M2 | 2 | GRID3 ingestion → Parquet; OCDS ingestion; HF Datasets repo + upload workflow | 167,002 segments and 3,233 label rows queryable in DuckDB |
| M3 | 3 | Imagery sampler, **one state pilot**; Open-Meteo weather ingest | Pilot features for one state; measured GB and runtime recorded |
| M4 | 4 | Full-scale feature build; dbt models + tests; Feast feature views | dbt `build` green with tests; Feast `apply` + historical retrieval works |
| M5 | 5 | Hazard model, temporal split, calibration, MLflow tracking | C-index/AUC on 2025 holdout reported and compared to baseline |
| M6 | 6 | Survival secondary (Cox PH, RSF, Schoenfeld); knapsack + sensitivity | Allocation table and marginal-value curve produced |
| M7 | 7 | MapLibre map, segment detail panel, budget control, GitHub Pages deploy | Live public URL; map renders on mobile at 375 px |
| M8 | 8 | Quarto report, model card, data dictionary, architecture diagram, cost analysis, demo video, Grafana dashboard, Dagster demo DAG | All §9 deliverables present; repo passes a cold-clone run |

Buffer: none built in. Expect M3 (imagery) and M8 (documentation + video) to be the two that overrun;
M8 can absorb one extra weekend without breaking the plan.

---

## 7. Data contracts

| Table | Grain | Key fields |
|---|---|---|
| `segments` | one row per road segment | `segment_id` (GRID3 `id`), geometry, `class`, `road_surface`, `speed_estimate`, `names`, `length_m`, `state`, `lga` |
| `labels` | one row per procurement event | `ocid`, `event_date`, `intervention_type`, `road_phrase`, `state`, `amount`, `match_confidence`, `segment_id` (nullable until matched) |
| `s2_features` | segment × month | `segment_id`, `month`, `ndvi_mean`, `ndvi_p05/p95`, `ndbi_mean`, `ndvi_trend_24m`, `ndvi_var_24m`, `ndbi_trend_24m`, `obs_count` |
| `weather_features` | grid cell × day → rolled to segment × month | `cell_id`, `rain_cum_30d`, `rain_max_7d`, `dry_spell_days`, `tmax_range`, `soil_moisture_sat_events` |
| `model_input` | segment × year | all features + `event_within_12m` (0/1), `year`, `split` |
| `predictions` | segment × scoring year | `segment_id`, `risk_12m`, `risk_decile`, `top_decile_flag` |
| `allocation` | scenario × budget | `budget_pct`, `segment_id`, `selected`, `cost`, `expected_value` |

Conventions: `segment_id` is the GRID3 `id`, never a surrogate. Dates ISO-8601. Naira amounts stored as
integers (kobo avoided — document the unit). All tables Parquet, partitioned by year where it helps.

---

## 8. Acceptance criteria

"Defensible" needs numbers, not adjectives. Targets on the 2025 temporal holdout:

| Metric | Target | Fails if |
|---|---|---|
| ROC-AUC (12-month intervention) | ≥ 0.70 | ≤ 0.60 |
| Lift over `class`-only baseline | ≥ +0.05 AUC | no lift — the satellite features add nothing |
| Top-decile capture | ≥ 3× base rate | < 2× |
| Calibration slope | 0.8–1.2 | outside, and unexplained |
| Precision@100 segments | reported, with CI | not reported at all |

If the model misses these, that is a **finding to publish**, not a failure to hide. The report explains
what was tried and why the signal is weak.

---

## 9. Deliverables

All six requested, plus the essentials:

| Artefact | Location | Notes |
|---|---|---|
| Model card | `docs/model-card.md` | Metrics, calibration, intended use, explicit non-goals, proxy-target disclaimer |
| Data dictionary | `docs/data-dictionary.md` | Every table/field, unit, provenance, refresh cadence, missingness |
| Architecture diagram | `docs/architecture.md` | Mermaid, built vs documented alternatives visually distinct |
| Cost analysis | `docs/cost-analysis.md` | Projected vs actual, proving $0 recurring |
| Quarto report | `reports/` | The narrative: problem → data → features → model → allocation → limits |
| Analysis notebooks | `notebooks/` | Working exploration that supports the Quarto narrative |
| Demo video | `docs/demo.mp4` or hosted link | 3–5 min: problem, map, budget control, honest limits |
| Label matching report | `docs/label-matching-report.md` | Gate G0 output |
| README | root | Quickstart, architecture, built-vs-documented table, live URL, licences |

---

## 10. Risks carried into the build

| Risk | Likelihood | Mitigation in this plan |
|---|---|---|
| Gate G0 fails (< 300 matches) | Medium | Committed stop rule; framing already survives a pivot to unsupervised degradation index |
| Event rate too low for stable estimates (1.9%) | High | Hazard model handles it; report CIs; do not over-claim precision; secondary survival analysis explicitly labelled as thin |
| Intervention ≠ failure | Certain | Target named as intervention need everywhere; construction events excluded; year fixed effects |
| Imagery backfill overruns (M3) | Medium | Pilot one state first and measure; national run is resumable and shardable by state |
| Six layers eat time before the model exists | High | Layers are built *behind* a working pipeline, in M4–M8, never as a precondition for M5 |
| Free-tier terms change mid-project | Medium | Re-verify DE Africa access, Actions policy and Open-Meteo terms at the start of each phase |
| HF Datasets bandwidth limits on a popular dashboard | Low | Dashboard reads pre-rendered tiles from GitHub Pages, not live Parquet from HF |
| Python 3.14 friction in transitive deps | Low | Top-level packages verified; pin the lockfile early in M1 |

---

## 10a. Re-scope after Gate G0 (2026-10-28)

Gate G0 **failed**: 181 high-confidence matches, against a threshold of 300 to continue.
Full diagnosis in `docs/label-matching-report.md`; the root cause is a data limit, not a matcher
defect — GRID3 names only 869 corridors and leaves 113,004 highway segments unnamed.

**Decision: model at corridor level, with an unsupervised degradation index as the primary
artefact and the 181 real interventions as external validation.**

### What changes

| Item | Before | After |
|---|---|---|
| Modelling unit | 167,002 segments | **869 named corridors** (18,419 km, all 37 states) |
| Primary method | Supervised discrete-time hazard | **Corridor degradation index** from satellite change; hazard model secondary |
| Label role | Training target | **Validation** — the index should rank known-intervention corridors highly |
| Supervised model | The headline | A secondary result on 181 positives, reported with confidence intervals and an explicit small-sample caveat |
| Map | Segment heatmap | 869 corridor lines, coloured by risk — legible at national scale |
| Optimisation | Knapsack over 167k segments | Knapsack over 869 corridors — faster, cleaner, and how budgets are actually decided |

### Why this is stronger, not weaker

- The metric that matters is defensible: *does the degradation index rank the 66 corridors that
  actually received maintenance above the 803 that did not?* That is a real, checkable claim.
- 36 corridors have **repeat** interventions, which supports a genuine (if small) survival analysis.
- Corridors are how contracts are written, so the analysis unit finally matches the decision unit.
- Nothing about the $0 constraint, the imagery plan or the pipeline changes.

### Revised thresholds

| Metric | Target |
|---|---|
| Mean risk percentile of the 66 labelled corridors | ≥ 70 (i.e. the index finds them) |
| AUC, labelled vs unlabelled corridor ranking | ≥ 0.60, with bootstrap CI |
| Supervised hazard on 181 positives | reported, **no minimum** — sample is too small to hold a bar |

---

## 11. Open questions

1. **Dagster vs Prefect for the demo DAG** — unanswered in the interview; defaulting to Dagster OSS.
   Confirm or overrule when M8 arrives.
2. **Whether the budget control should also show naira** — you chose percentage of network. A secondary
   naira label could help a Nigerian audience; confirm before M7.
3. **Scope outcome of Gate G0** — necessarily unknown until M1 completes. Milestones M2–M8 assume
   national scope for sizing but do not assume a specific state list.

---

## 12. Out of scope

Citizen reporting / user submissions. Real-time traffic. Satellite radar (Sentinel-1). Bridge and
culvert condition. Anything requiring a paid API, a credit card, or a private dataset. Any claim of
temporal accuracy finer than annual. Any deployment target other than GitHub Pages.

---

## 13. Preflight housekeeping (do in M1)

`knowledge.md` currently contradicts itself: it corrects the Copernicus access story and the survival
framing, but still carries stale bullets saying "Evaluation must be temporal: train 2022–2024",
"2,000 min/month" for Actions, "use Sentinel-2 L2A cloud masks", and the S3 GET cost trap. Before any
code is written, remove or fix those four bullets so the repo has one consistent story. Likewise
`AGENTS.md` is still an empty stub and should point at this spec.
