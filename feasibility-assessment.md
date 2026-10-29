# RoadSense Nigeria — Feasibility Assessment

Date: 2026-10-28. Scope: can this project be built as specified, and what must change.
Every number below marked **[measured]** was produced by querying the live source on 2026-10-28,
not estimated. Estimates are labelled **[estimate]**.

---

## 1. Verdict

**Feasible, with two substantive re-scopes and one hard gate.** The engineering is comfortably
achievable at $0. The *science claim* — "predict time-to-failure per segment" — is not supportable on
the available labels, and must be re-framed. One gate decides go/no-go: whether the 3,233 procurement
records can be matched to road segments at useful precision.

| Layer | Feasible? | Notes |
|---|---|---|
| 1 Data sources | **Yes, with corrections** | Access model in the spec is wrong for Copernicus. DE Africa is better than the spec realises. |
| 2 Ingestion | **Yes** | GitHub Actions limitation in the spec is wrong — public repos are unlimited, not 2,000 min. |
| 3 Orchestration | Yes | Prefect free tier is smaller than claimed, but adequate. |
| 4 Storage | **Yes** | R2 10 GB verified. Workload fits in well under 1 GB of analytical output. |
| 5 Transformation | Yes | dbt/DuckDB both fine. No blockers found. |
| 6 Feature engineering | **Yes** | Verified pre-computed monthly cloud-free mosaics exist — this removes the hardest part. |
| 7 Survival modelling | **Ambiguous** | Libraries are healthy. The *labels* will not support the stated model. See §4. |
| 8 Optimisation | **Yes** | Budget amounts present for 100% of candidate rows; traffic proxy needs substitution. |
| 9 Serving | Yes | No blockers found. |

---

## 2. Evidence log

### GRID3 NGA Roads v1.0 — better than the spec assumes

Queried the live FeatureServer (`services3.arcgis.com/BU6Aadhn6tbBEdyk/.../GRID3_NGA_roads/FeatureServer`).

**[measured]** Total segments: **6,274,965** — the spec's "6.2M" is accurate.
**[measured]** Fields: `id, country, iso3, source_id, class, speed_estimate, speed_estimate_method,
road_surface, names, subclass, speed_limits, date, source_acronym, Shape__Length`.

Two of these matter more than the spec realises:

- `names` exists — road-name matching against procurement text is possible, not just geometric matching.
- `speed_limits` and `speed_estimate_method` exist, so the "speed estimate" claim is real.

**[measured]** Segment counts by class:

| class | n | | class | n |
|---|---:|---|---|---:|
| residential | 3,837,761 | | path | 62,418 |
| unclassified | 868,542 | | **primary** | **56,262** |
| track | 836,650 | | **trunk** | **38,074** |
| unknown | 283,457 | | **motorway** | **2,362** |
| tertiary | 136,898 | | footway | 6,105 |
| service | 74,103 | | others | < 2,000 |
| **secondary** | **70,304** | | | |

Motorway + trunk + primary + secondary = **167,002**. The spec's "150,000–200,000 segments" is right.
Access is anonymous, no auth, CC BY-SA 4.0. **No issue.**

### Digital Earth Africa — the unlock the spec misses

The spec's Stage 1 reads Sentinel-2 Red/NIR per segment per week via CDSE STAC. That is the single
biggest technical risk in the document, and it is avoidable.

**[measured]** DE Africa publishes **Sentinel-2 Rolling Monthly GeoMAD**: 10 m, 14 bands,
EPSG:6933, monthly 3-month rolling cloud-free composites, **2019–present**, 1-month latency, plus
annual and semiannual variants.
**[measured]** Anonymous range reads work: `deafrica-services.s3.af-south-1.amazonaws.com` returned
HTTP 206 with valid COG (`II*\0`) magic bytes, **no AWS account, no credentials, no token**.
**[measured]** Latency from this workstation: ~440 ms per 64 KB range request (~1.0 s cold).

This means cloud masking, multi-temporal compositing and scene selection — the part of the pipeline
that eats both quota and engineering time — are **already done upstream**. We read one COG window per
segment-month instead of scoring dozens of scenes.

### Copernicus CDSE — the spec's access claim is wrong

**[measured]** Free tier ("Copernicus General User"), from the official quotas page:

| Interface | Free monthly quota |
|---|---|
| Sentinel Hub APIs | **10,000 requests**, **10,000 processing units**, 300 PU/min |
| Direct HTTP to COGs | 50,000 requests |
| openEO | 10,000 credits, 12 req/min, 2 concurrent |
| S3 / OData / STAC | 12 TB transfer, 4 concurrent conns, 20 MB/s per conn |

And explicitly: *"Note that there are APIs that are not available to Copernicus General Users such as
Sentinel Hub Batch Processing API."*

Consequences:
1. An account and an OAuth client **are** required — the spec's "no API keys required for the core
   pipeline" is false as written.
2. 167k segments × 24 months = **4.0M segment-months**. Even at one request each, that is 400× the
   10,000-request Sentinel Hub quota. At weekly resolution (24 months ≈ 104 weeks ≈ 17.4M samples)
   it is ~1,700× over.
3. Batch processing — the only sane way to do this at scale — is unavailable free.

**The plan in the spec cannot run on CDSE's free tier by roughly two to three orders of magnitude.**

### Labels — the crux, measured

Downloaded the full Nigeria OCDS dataset (`data.open-contracting.org` publication 64, sourced from
NOCOPO/BPP, retrieved 2026-10-20) and analysed it.

**[measured]** 98,866 contracting processes, May 2021 – Oct 2026. 10.0% (9,862) mention roads.
Filtered to the two relevant buyers and road keywords:

- FERMA processes: 2,196 · Federal Ministry of Works: 4,641
- FERMA ∧ road: 1,479 · FMW ∧ road: 1,754
- **Candidate label rows: 3,233**

What that 3,233 looks like:

| Property | **[measured]** value | Implication |
|---|---|---|
| Coordinate / geometry fields | **none exist in the dataset** | Matching must be by name + state, not point-in-polygon. |
| Rows naming a Nigerian state | 2,632 (81.4%) | Coarse geolocation is recoverable for 4 in 5 rows. |
| Amount present | 3,233 (100% planning budget); 688 tender value | Cost inputs exist, but are budgeted not actual, and project-level not per-km. |
| Unique project titles | 2,974 of 3,233 | Only ~223 repeat titles ⇒ almost no road has two dated interventions. |
| Years present | 2021: 804, **2022: 0**, 2023: 221, 2024: 1,288, 2025: 920, 2026: 0 | The stated "train 2022–2024 / validate 2025–2026" split is **impossible**: 2022 is empty and 2026 has three rows project-wide. |

Titles are usable and specific — e.g. *"SPECIAL REPAIRS OF KATSINA-DAURA-MASHI ROAD KATSINA STATE"*,
*"MAJOR MAINTENANCE OF OKWELLE-OJIAMA-IDEATO ROAD IN IMO STATE"*. These are exactly the event records
needed. There are simply not many of them, and they cluster in 2024–2025.

### Free-tier claims, corrected

| Spec claim | Reality |
|---|---|
| GitHub Actions: 2,000 min/month for public repos | **[verified]** Public repos are **free and unlimited** on standard hosted runners. Understated. Note: from 2026-03-01 a $0.002/min platform charge applies — but public repos remain free. |
| Prefect Cloud: 100,000 runs/month | Free "Hobby" tier is free-forever but ~1 workspace, ~5 deployments, ~500 managed compute minutes/month. Adequate for a weekly DAG; the run-count figure is wrong. |
| Open-Meteo: 10,000 calls/day | **[verified]** Correct — but **non-commercial use only** (10k/day, 5k/hr, 600/min). Fine for a portfolio; a genuine $0 blocker if this ever becomes commercial. |
| Cloudflare R2: 10 GB, zero egress | **[verified]** 10 GB-month, 1M Class A, 10M Class B, zero egress. |
| Copernicus: no API keys | Wrong — account + OAuth client required. |
| Planetary Computer: free | STAC metadata is open; **data assets need a signed token**, and Microsoft is steering users to Azure "Planetary Computer Pro". Treat as a risk, not a foundation. |

---

## 3. Sizing

**[estimate]** Using the rolling monthly GeoMAD path with tile-grouped sampling:

- Nigeria at 10 m in EPSG:6933 covers roughly **90–110 COG tiles**; 167k segments ≈ 1,700 per tile.
- Sampling per tile-month: request the distinct 512 px blocks containing segments (~800–1,200 per
  tile per band) rather than one request per segment.
- Backfill: 95 tiles × 24 months × 2 bands × ~1,000 blocks ≈ **4.6M range requests**. Serial at
  440 ms that is ~560 hours; with 32–64 way concurrency, **9–18 hours wall clock**. One-off.
- Monthly increment: **~1–2 hours** — comfortably inside free Actions minutes.
- Egress: ~300 GB from a public AWS bucket (no charge to us, no requester-pays).
- Analytical output: 167k × 24 × ~20 features ≈ 320 MB raw → **~80 MB Parquet**. Fits R2's 10 GB
  with three orders of magnitude of headroom.

Conclusion: **compute is not the constraint.** The spec's per-scene, per-request design is; the
mosaic-first design is not.

---

## 4. The three real risks

### R1 — Label volume may be too small to model (blocking)

3,233 candidate events against 167,002 candidate segments is a **1.9% event rate**, and after
name-matching plus state disambiguation the usable count will be lower — plausibly 800–2,000.
Survival models tolerate low event rates, but the *paired-interval* structure does not: a
time-to-failure model needs, per road, a start (last intervention or series start) and an end (next
intervention). With only ~223 repeated titles, most roads contribute exactly one interval, and that
interval is almost always right-censored at the observation window edge.

**Mitigation:** drop continuous-time survival as the primary framing. Use **discrete-time hazard** —
one row per segment-year, label = "intervention occurred in the following 12 months", fit logistic /
gradient-boosted classifier, evaluate with time-based split (train 2023–2024, test 2025). This is
statistically honest, needs no pairing, uses every one of the 3,233 rows, and still produces a
per-segment annual failure probability — which is exactly what the optimiser needs. Report Cox PH /
RSF as a secondary analysis on the subset with genuine repeat events, labelled as such.

### R2 — "Failure" is being measured as "spending" (conceptual, needs an honest answer)

A FERMA/FMW contract means *money was allocated*, not *the road failed*. Allocation is political and
budget-cyclical: **[measured]** 1,288 events in 2024 versus 221 in 2023 and zero in 2022. A model
trained on this learns where the ministry spent, which correlates with need but is not the same thing.
Worse, censoring is **informative** — a road with no record may be pristine or simply unfunded.

**Mitigation, stated openly in the README and model card:** restrict to *maintenance/rehabilitation*
events and exclude new construction and access roads (the raw text includes "Construction of Access
Road to SHQ office Complex" — pure noise for a road-failure model). Add year fixed effects to absorb
budget cycles. Report the target as a **proxy for intervention need**, and quantify the bias by
checking whether 2024-heavy training data shifts predictions. Do not claim to predict physical road
failure. This is the difference between a defensible project and one a reviewer dismantles.

### R3 — Value proxy for the optimiser has no Nigerian source

The optimiser maximises failure-probability × (traffic × length), but no free Nigerian AADT dataset
was found. GRID3 carries `speed_estimate`, not volume.

**Mitigation:** substitute (a) the global extra-urban AADT time series of van Strien et al. 2024
(Scientific Data, open), acknowledging coarse accuracy for West Africa, or (b) GRID3 settlement
population within a 5 km catchment × segment length. Either is defensible if labelled as a proxy and
if the sensitivity analysis in Stage 7 reports how the allocation changes under both. Do not present
traffic-based value as measured.

---

## 5. Go / no-go gate

**Gate G0 (1 week, decide before building anything else):** take the 3,233 rows, extract the road
phrase and state, and attempt to match to GRID3 `names` within the state's bounding box, with a
confidence score.

- **≥ 800 high-confidence matches** → proceed. Labels are workable; build the pipeline.
- **300–800** → proceed, but national coverage is not defensible; scope to the states that survive
  and say so.
- **< 300** → **stop.** Re-scope to a pure "satellite degradation + budget optimisation, illustrative
  labels" demo, or pick a different sector. Do not spend twelve weeks discovering this at layer 7.

This gate is cheap (days) and it de-risks the only part of the project that cannot be engineered
around. Everything else — imagery, weather, storage, modelling code, dashboard — is known-good.

---

## 6. Recommended re-scope

Keep the 9-layer story for the portfolio narrative; build a 5-layer MVP first.

**MVP (6–8 weeks part-time):**
1. Ingest GRID3 trunk/primary/secondary into DuckDB (167k segments) — half a day.
2. `names`-based road gazetteer + procurement-event matcher (Gate G0) — 1 week.
3. Sample NDVI/NDBI from DE Africa rolling monthly GeoMAD, tile-grouped, 2023-01 → 2026-09 — 1 week.
4. Weather per 1° cell from Open-Meteo (non-commercial, ~150 calls) — 1 day.
5. Discrete-time hazard model + calibration + top-decile capture — 1–2 weeks.
6. Knapsack with PuLP, sensitivity across ₦10B/25B/50B/100B — 3 days.
7. Static MapLibre or Streamlit dashboard over Parquet — 1 week.

**Defer to "phase 2" (narrative polish, not dependencies):** Prefect/Dagster, dbt, Hopsworks, MLflow,
OpenTofu, Grafana, Cloudflare Workers API. Each adds surface area without improving the model, and
the spec's own deliverables checklist does not require them.

**Scope down the universe too.** A defensible national model on 167k segments with 1.9% events is
hard; a defensible model on the ~40k trunk+primary segments in 12–15 states with the best label
coverage is achievable. Reviewers reward honest scoping over silent gaps.

---

## 7. Effort estimate

**[estimate]** Part-time, single experienced practitioner:

| Work | Weeks |
|---|---|
| Gate G0: label extraction + matching | 1 |
| Ingestion + storage + weather | 1.5 |
| Feature engineering from GeoMAD | 1.5 |
| Modelling, validation, model card | 2.5 |
| Optimisation + sensitivity | 0.5 |
| Dashboard + serving | 1.5 |
| Documentation, diagram, video | 1 |
| **Total** | **~9.5** |

Add 50% for the parts that always overrun (label matching edge cases, cloud/parquet debugging,
making the map look credible). Realistic: **12–15 part-time weeks**. The spec implies a similar
amount of work but front-loads the optional infrastructure; if built as written, the 9 layers alone
consume the first six weeks before a single model exists.

---

## 8. Bottom line

The project is buildable and the $0 constraint holds — but the spec is wrong in three specific,
fixable places (Copernicus access, the label timeline, and the survival framing), and right about one
thing it under-uses: Digital Earth Africa already publishes the monthly cloud-free 10 m composites
this pipeline needs, anonymously and at zero cost.

Run Gate G0 first. Everything downstream is engineering that can be estimated with confidence; label
matching is the only part that can kill the project, and it is the cheapest thing to test.
