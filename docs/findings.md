# Findings register

Every factual claim here was measured against a live source on **2026-10-28**, unless marked
**[estimate]**. Where a finding contradicts the original project proposal
(`#FermaCloud Engineering.txt`), the finding wins — the proposal's figures were not verified.

Purpose of this document: stop us re-deriving facts, and stop the project from drifting back onto
assumptions that have already been shown to be false.

---

## F0 — Summary of the five findings that change the project

| # | Finding | Effect |
|---|---|---|
| F1 | Copernicus CDSE free tier cannot serve this workload — off by 2–3 orders of magnitude, and the Batch API is unavailable free | The per-scene imagery plan is dead; replaced by DE Africa mosaics |
| F2 | Digital Earth Africa publishes pre-computed monthly cloud-free 10 m composites, anonymously accessible | Removes cloud masking and compositing entirely — the hardest engineering |
| F3 | Only 3,233 FERMA/FMW road interventions exist in the open procurement record, with **no coordinates** and **no 2022 or 2026 data** | The specified train/validate split is impossible; "time-to-failure" is not supportable |
| F4 | Only **32.3%** of highway segments carry a name, and name is the only join key to labels | The matched universe is ~54k segments, not 167k |
| F5 | Cloudflare R2 requires a payment method to enable | Storage moved to Hugging Face Datasets to preserve the no-card rule |
| F13 | The 2024 procurement spike is 40% new construction and 34% noise | The budget-cycle confound is weaker than feared; 2025 now dominates the labels |
| F14 | All 869 corridors have geometry; 2.74 MB raw, 0.64 MB gzipped | The national map needs no vector-tile pipeline |
| F16 | The "20 m is 10× cheaper" plan was wrong by ~9×; 20 m costs 857 KB per 8 km tile vs 934 KB at 10 m | Sampler defaults to 40 m; national backfill is ~31 GB, not 13 |
| F17 | Centreline NDVI on a road is ≈ 0 — it measures asphalt | Phase 4 needs a road-versus-verge contrast, not a centreline band |
| F19 | The contrast feature is trustworthy at 10 m but flips sign on 1 in 5 corridor-months at 40 m | The condition signal must run at 10 m (~70 GB), while a landscape index can run at 40 m (31 GB) |
| F20 | 869 GRID3 names are **850 corridors**: 18 slugs were shared by case/punctuation variants, so `corridor_id` was not unique and the first real backfill merge refused to run | Corridors are grouped by slug with the other spellings kept as aliases; the merge gate stays strict |

---

## F1 — Copernicus CDSE free tier is not viable

**Source:** `documentation.dataspace.copernicus.eu/Quotas.html` (Copernicus General User table).

| Interface | Free monthly quota |
|---|---|
| Sentinel Hub APIs | 10,000 requests · 10,000 processing units · 300 PU/min |
| Direct HTTP to COGs | 50,000 requests |
| openEO | 10,000 credits · 12 req/min · 2 concurrent |
| S3 / OData / STAC | 12 TB transfer · 4 concurrent connections · 20 MB/s per connection |

Direct quote from the page: *"Note that there are APIs that are not available to Copernicus General
Users such as Sentinel Hub Batch Processing API."*

**Arithmetic:** the proposal's Stage 1 reads Red and NIR per segment per week.
167,002 segments × 104 weeks = **17.4M requests** against a 10,000-request allowance — roughly
**1,700× over quota**, before counting processing units. Even at one request per segment-month it is
~400× over.

**Also false:** the proposal claims "no API keys required for the core pipeline". CDSE requires an
account and an OAuth client for Sentinel Hub; STAC metadata is open, data access is not.

**Decision:** CDSE is not used for the pipeline. It remains a documented alternative only.

---

## F2 — Digital Earth Africa already publishes what we need

**Source:** DE Africa STAC (`explorer.digitalearth.africa/stac`), collection `gm_s2_rolling`;
documentation at `docs.digitalearthafrica.org/en/latest/data_specs/GeoMAD_specs.html`.

**Service specs:** Sentinel-2 Rolling Monthly GeoMAD — 10 m, 14 bands, EPSG:6933, monthly
three-month rolling cloud-free composites, 2019–present, 1-month latency. Annual and semiannual
variants also operational; Landsat variants date back to 1984.

**Measured access:** `deafrica-services.s3.af-south-1.amazonaws.com` returns HTTP 206 to anonymous
range requests, with valid COG magic bytes (`II*\0`). No AWS account, no credentials, no token, no
requester-pays flag.

**Measured file geometry** (one band, one 96 × 96 km tile, 2024-01):
- Image 9600 × 9600 px @ 10 m; file size 172 MB.
- Internal tile **800 × 800 px** (8 km); **~886 KB compressed per internal tile** (min 861 KB, max
  939 KB, 144 tiles).
- Overviews at 4800 / 2400 / 1200 / 600 / 300 px; **~92 KB per tile at 20 m**.
- Range-request latency from this workstation: **~440 ms per 64 KB**.

**Why the internal tile size matters:** HTTP range reads fetch a whole 800 × 800 tile. Reading a
single 100 m road buffer still costs 886 KB at full resolution — 14× the buffer's own content.
Therefore sample **per 8 km tile, not per segment**: one read serves every segment inside that tile.

**Why the overview matters:** at 20 m an internal tile is ~92 KB instead of ~886 KB — a **~10×
reduction for identical wall-clock time**, because these reads are latency-bound, not
bandwidth-bound. A 100 m road buffer is still 5 × 5 pixels at 20 m, which is ample for a stable mean
NDVI.

**Decision:** sample from GeoMAD at the 20 m overview, grouped by 8 km tile. Bands B04 (red), B08
(NIR), B11 (SWIR) — NDVI needs the first two, NDBI the last two.

---

## F3 — Labels: thin, unlocated, and hole-in-the-middle

**Source:** Nigeria OCDS, Bureau of Public Procurement / NOCOPO, `data.open-contracting.org`
publication 64. Full CSV bundle downloaded (22.6 MB compressed), retrieved by the publisher
2026-10-20.

**Volume:** 98,866 contracting processes, May 2021 – Oct 2026. 9,862 (10.0%) mention roads at all.

**Narrowed to usable events:**

| Filter | Count |
|---|---|
| FERMA processes | 2,196 |
| Federal Ministry of Works processes | 4,641 |
| FERMA ∧ road keywords | 1,479 |
| FMW ∧ road keywords | 1,754 |
| **Union — candidate labels** | **3,233** |

**Structure of the 3,233:**

| Property | Measured | Consequence |
|---|---|---|
| Coordinate / geometry field | **does not exist** | Matching must be textual + state-constrained |
| Rows naming a Nigerian state | 2,632 (81.4%) | Coarse location recoverable for 4 in 5 |
| Unique project titles | 2,974 of 3,233 | ~223 repeat titles ⇒ almost no road has two dated events |
| `planning_budget_amount` present | 3,233 (100%) | Cost inputs exist (budgeted, not actual) |
| `tender_value_amount` present | 688 (21%) | Sparse second cost source |

**Year distribution — the killer:**

| Year | Events |
|---|---|
| 2021 | 804 |
| **2022** | **0** |
| 2023 | 221 |
| 2024 | 1,288 |
| 2025 | 920 |
| **2026** | **0** |

The proposal's "train 2022–2024, validate 2025–2026" is **impossible**: 2022 is empty and 2026 has
three rows project-wide.

**Sample titles** (real, unedited):
- `SPECIAL REPAIRS OF KATSINA-DAURA-MASHI ROAD KATSINA STATE`
- `MAJOR MAINTENANCE OF OKWELLE-OJIAMA-IDEATO ROAD IN IMO STATE`
- `GENERAL MAINTENANCE OF KARLIHI-JADA ROAD IN ADAMAWA`
- `Construction of Access Road to SHQ office Complex at Lokoja` ← noise, must be excluded
- `All-in-one solar powered street light in Tonex Road Egelebie` ← noise, must be excluded

**Decision:** discrete-time hazard on segment-year rows, label = intervention within 12 months,
train 2023–2024, test 2025. Every one of the 3,233 rows is usable; no pairing required.

---

## F4 — Only a third of highway segments are named

**Source:** GRID3 NGA Roads v1.0 FeatureServer,
`services3.arcgis.com/BU6Aadhn6tbBEdyk/arcgis/rest/services/GRID3_NGA_roads/FeatureServer/0`.

| Query | Count |
|---|---|
| All segments | **6,274,965** |
| motorway + trunk + primary + secondary | **167,002** |
| …of those, `names` not null | 167,002 |
| …of those, `names` non-empty | **53,998 (32.3%)** |

**Class distribution of the full network:**

| class | n | | class | n |
|---|---:|---|---|---:|
| residential | 3,837,761 | | path | 62,418 |
| unclassified | 868,542 | | **primary** | **56,262** |
| track | 836,650 | | **trunk** | **38,074** |
| unknown | 283,457 | | footway | 6,105 |
| tertiary | 136,898 | | **motorway** | **2,362** |
| service | 74,103 | | living_street | 1,480 |
| **secondary** | **70,304** | | others | < 600 |

**Fields available:** `id, country, iso3, source_id, class, speed_estimate,
speed_estimate_method, road_surface, names, subclass, speed_limits, date, source_acronym,
Shape__Length`.

**Important:** `names` is NOT NULL for all 167,002 rows but is an **empty string** for 113,004 of them.
Querying `names IS NOT NULL` therefore overcounts; the usable filter is `names <> ''`.

**Consequence for Gate G0:** name-based matching can reach at most 53,998 segments. The matched
universe is therefore ~54k, not 167k — which *raises* the effective event rate and makes the
modelling problem easier, at the cost of national coverage. Propagating labels from named segments
onto contiguous unnamed segments of the same class is the phase-2 improvement, not a G0 requirement.

**Measured payload:** 2,000 features with geometry at precision 4 = 1.5 MB, so ~27 paged requests and
~41 MB for all named highway segments. Centroids are not available (`returnCentroid` is rejected —
polyline layers do not support it), so geometry must be fetched and reduced locally.

---

## F5 — Storage: R2 is out, Hugging Face Datasets is in

**Source:** Cloudflare community and billing reports, 2026. Enabling R2 requires a payment method on
the account, even when usage stays inside the free tier, and usage beyond the free allocation is
billed rather than capped. At least one user reports an immediate $5 charge on activation.

The free tier itself is genuine and generous — 10 GB-month, 1M Class A, 10M Class B, zero egress —
but the signup gate breaks the "no credit card at any point" constraint.

**Decision:** Hugging Face Datasets (free public hosting, no card). Estimated output is well under
500 MB, so this is comfortable. Documented alternative: R2, if a card ever becomes acceptable.

---

## F6 — Free-tier facts, corrected

| Claim in the proposal | Verified reality | Effect |
|---|---|---|
| GitHub Actions: 2,000 min/month for public repos | Public repos get **unlimited** standard-runner minutes; 2,000 applies to **private** repos | Understated benefit. Note: a $0.002/min platform charge landed 2026-03-01 for non-free contexts; public repos remain free |
| Prefect Cloud: 100,000 runs/month | Hobby is free-forever but ~1 workspace, ~5 deployments, ~500 managed compute min/month | Adequate for a weekly DAG; the figure is wrong |
| Open-Meteo: 10,000 calls/day | Correct — but **non-commercial use only**, plus 5k/hour, 600/min | Fine for a portfolio; a real blocker if this is ever monetised |
| Cloudflare R2: 10 GB, zero egress | Correct, **but a payment method is required to enable** | Rejected (see F5) |
| Copernicus: no API keys | Wrong — account + OAuth client required | See F1 |
| Planetary Computer: free | STAC metadata open; **data assets need a signed token**; Microsoft is steering users to Azure "Planetary Computer Pro" | Risk, not a foundation |
| GRID3: ~6.2M segments, free, no auth | **6,274,965**, anonymous, CC BY-SA 4.0 | Confirmed |

---

## F7 — Value proxy has no Nigerian source

No free Nigerian AADT / traffic-volume dataset was located. GRID3 carries `speed_estimate`, not
volume, so it cannot stand in.

**Substitutes, both to be labelled as proxies:**
1. van Strien et al. 2024, *A global time series of traffic volumes on extra-urban roads*
   (Scientific Data) — global extra-urban AADT; coarse accuracy for West Africa.
2. GRID3 settlement population within a 5 km catchment × segment length.

**Decision:** report both; do not claim measured traffic. The budget control is expressed as
**percentage of network fundable**, which also sidesteps currency arguments.

---

## F8 — Toolchain verified on this machine

Python **3.14.4**, pandas **3.0.3**. All top-level packages resolve as binary wheels:

`rasterio 1.5.2` · `geopandas 1.2.0` · `pyproj 3.8.0` · `shapely 2.2.0` · `duckdb 2.0.0` ·
`rioxarray 0.23.0` · `feast 0.67.0` · `dagster 1.13.27` · `mlflow 3.17.2` ·
`scikit-survival 0.28.0` · `lifelines 0.30.3` · PuLP (bundles CBC).

No Python-version blocker. **Caveat:** `duckdb 2.0.0` is a major release — follow current docs, not
1.x tutorials, and expect API differences in anything copied from old blog posts.

---

## F9 — Corrections still to apply to older documents

`knowledge.md` currently carries both the corrected findings and four stale bullets inherited from the
proposal. These must go before the repo has a public face:

1. "Evaluation must be temporal: train 2022–2024, validate 2025–2026" — contradicts F3; the correct
   split is train 2023–2024, test 2025.
2. "GitHub Actions … 2,000 min/month" — contradicts F6.
3. "Sentinel-2 cloud cover … use multi-temporal compositing and L2A cloud masks" — superseded by F2;
   DE Africa does this upstream.
4. "Cost traps: S3 GET overruns" — refers to a storage path we no longer use.

`AGENTS.md` is still an empty stub.

---

## F11 — Gate G0 result: STOP (measured)

Gate G0 ran end to end on 2026-10-28 via `scripts/run_gate0.py`. **Verdict: STOP**, against the
threshold committed to in advance.

| Metric | Result |
|---|---:|
| Named highway segments | 53,998 |
| Maintenance events extracted from OCDS | 1,672 |
| Matched at high confidence | **181** |
| Matched at medium confidence | 131 |
| Matched at low confidence | 563 |
| Unmatched | 797 |
| Unique corridors with a high-confidence event | 66 |
| Threshold to proceed | 800 |
| Threshold to proceed conditionally | 300 |

### The decisive cause: GRID3 names very few corridors

53,998 named highway segments carry only **869 distinct corridor names**, and the remaining
**113,004 highway segments have an empty name**. The most frequent names are corridors, not
segments — `Kano-Maiduguri Highway` covers 1,255 segments, `Enugu - Port Harcourt Expressway` 1,104.

The whole named network therefore offers a vocabulary of **936 distinct place tokens**. Procurement
text can only be joined to that vocabulary if the road in the contract is one of those 869 corridors.

### Why the other 797 events failed

| Reason | Events | Interpretation |
|---|---:|---|
| Road absent from GRID3 names entirely | 426 | No token in the phrase appears in *any* named road in the country. Not fixable by better matching. |
| Only one token shared with any road name | 285 | One shared token cannot establish identity without guessing. |
| Tokens aligned but below threshold | 86 | Genuinely ambiguous; correct to reject. |

### Matcher iterations, reported honestly

The first implementation produced 166 high-confidence matches. Two genuine defects were found and
fixed, lifting it to 181:

1. **State was a hard filter.** Nigerian highways cross state lines — `Abuja-Keffi Expressway`
   appears in the contract as FCT but GRID3 places its segments in Nasarawa. Cross-state matches are
   now allowed when at least three tokens agree.
2. **The phrase window admitted noise** — `republic`, `border`, `international` were being treated as
   place names.

A further diagnostic pass (relaxing the state filter entirely and re-scoring all 797 unmatched
events nationally) found only ~23 additional high-confidence candidates. **The ceiling is therefore
roughly 200, not 300+, and it is a data limit rather than a matcher defect.**

This distinction matters: the gate is not failing because the code is weak, but because the open
procurement record names roads that the open road network does not name.

---

## F12 — The corridor table (post-gate re-scope)

Built by `scripts/build_corridors.py` from the 53,998 named segments.

| Metric | Value |
|---|---:|
| Corridors | **869** |
| Total named length | **18,419 km** (~51% of the ~36,000 km federal network) |
| Median corridor length | 4.57 km |
| States covered | 37 (all) |
| Corridors with ≥1 high-confidence intervention | 66 |
| Corridors with ≥2 interventions (repeat events) | **36** |
| Labelled events | 181 |

> **Superseded on the count by F20 (2026-10-30):** 869 distinct *names* collapse to **850 corridors**
> once case/punctuation variants are merged, which is what the table holds. Length (18,419.1 km),
> labels (66 corridors / 181 events) and coverage are unchanged by the merge.

**Why corridors are the right unit now:** the 181 signatures spread across 850 corridors × 3 usable
years gives roughly a 7% per-corridor-year event rate — far more workable than 181 against 167,002
segments. The 36 repeat-event corridors are the only subset that can support a genuine survival
analysis, and they should be reported as such.

The generous corridors are long inter-city routes: `Onitsha - Owerri Road` (166 km, 10 events),
`Gombe - Potiskum Road` (163 km, 8 events), `Gombe - Biu Road` (140 km, 8 events).

---

## F13 — The 2024 procurement spike is mostly construction, not maintenance

Measured 2026-10-29 by re-classifying every buyer-and-road candidate from the OCDS bundle. This
matters because F3 reported a 2024 spike (1,288 events against 221 in 2023) and flagged it as a
budget artefact that would confound a model. Most of that spike is not maintenance at all.

| Year | Construction | Maintenance | Noise | Other | Total |
|---|---:|---:|---:|---:|---:|
| 2021 | 433 | **494** | 142 | 48 | 1,117 |
| 2022 | — | **0** | — | — | **0** |
| 2023 | 40 | **230** | 28 | 2 | 300 |
| 2024 | 667 | **315** | 567 | 124 | 1,673 |
| 2025 | 173 | **997** | 28 | 2 | 1,200 |
| **Total** | 1,313 | **2,036** | 765 | 176 | 4,290 |

**2024 is 40% new construction and 34% noise.** Once `classify_intervention` runs, the maintenance
series is 494 / 0 / 230 / 315 / 997 — a climb, but nothing like the 4× jump F3 implied. The 2024
anomaly in the *raw candidate* set is a capital-works bulge, not a burst of roads needing repair.

**Consequences:**

1. Risk R2 (budget cycles masquerading as need) is **weaker than feared** for the maintenance
   target specifically. Year fixed effects stay in, but they are no longer load-bearing.
2. The 2025 peak (997, 49% of all maintenance events) is the real distributional problem: half of
   all labels sit in the most recent year, which is also the year the temporal test set uses. A
   train-2023–24 / test-2025 split will have ~545 training events against ~997 test events. That
   imbalance must be reported, not smoothed away.
3. F3's 3,233 candidate count and the 4,290 here differ because F3 used a stricter buyer list. Both
   reduce to the same **2,036 maintenance events**, so the operative number is unchanged.

---

## F14 — Corridor geometry: all corridors, 2.74 MB

Measured 2026-10-29 via `scripts/build_geometry.py`. Rebuilt after the F20 merge: **850/850
corridors**, same 127,091 vertices, 2.73 MB.
 The Gate G0 segment table kept only centroids,
which is enough to match but not to draw, so geometry was refetched and merged by corridor name.

| Metric | Value |
|---|---:|
| Corridors in table | 869 |
| Corridors with geometry | **869 (100%)** |
| Paths merged | 54,020 |
| Vertices before simplification | 270,949 |
| Vertices at 0.0001° tolerance (~11 m) | 127,091 |
| GeoJSON on disk | **2.74 MB** |
| Same file gzipped | **0.64 MB** |
| Extent | lon 2.732–14.220, lat 4.606–13.061 (Nigeria is ~2.7–14.7 E, 4.3–13.9 N) |

Tolerance sweep, to show the choice was measured rather than guessed:

| Tolerance | Vertices | Size |
|---|---:|---:|
| none | 270,949 | 5.36 MB |
| 0.00005° | 139,540 | 2.97 MB |
| **0.0001°** | **127,091** | **2.74 MB** |
| 0.0003° | 116,241 | 2.54 MB |
| 0.001° | 110,710 | 2.44 MB |

**The curve flattens after 0.00005°**: most remaining vertices are genuine road curvature, not
redundant collinear points, so tighter simplification buys ~0.3 MB and costs real shape. 0.0001° is
the chosen default. At 0.64 MB gzipped, the whole national corridor layer is a smaller download
than one page of a typical photo gallery — GitHub Pages serves it without a vector-tile pipeline,
which removes a build step that would otherwise be needed in Phase 7.

---

## F15 — Anonymous Hugging Face reads work, including range requests

Measured 2026-10-29 against a public dataset file
(`nyu-mll/glue/resolve/main/README.md`): HTTP **206** to a bytes-0-1023 range request, with no token
and no account.

That is the same access pattern the pipeline needs, and it matters twice: a stranger cloning the
repo can fetch the published tables with a plain `pd.read_parquet(url)`, and DuckDB's `httpfs`
can range-read parquet over the same endpoint. **Publishing still requires `HF_TOKEN`** — the
asymmetry is deliberate and is why the read path has no dependency on `huggingface_hub` at all.

---

## F16 — F2's imagery cost conclusion was wrong by ~9×

Measured 2026-10-29 with a counting proxy in front of the S3 endpoint, so these are real response
bodies rather than arithmetic.

F2 recorded "~886 KB per internal tile at 10 m" and "~92 KB per tile at 20 m", and concluded that
sampling at 20 m was a **~10× saving**. That comparison was between one base tile and one overview
tile — but they do not cover the same ground. The base image is tiled at **800 × 800 px** (8 km at
10 m) while every overview is tiled at **256 × 256 px**. At 20 m a 256 px tile covers only 5.12 km,
so an 8 km footprint needs **nine** overview tiles, not one.

| Analysis resolution | Bytes per 8 km tile, one band | vs 10 m |
|---|---:|---:|
| 10 m (base) | **933,888** | 1.00× |
| 20 m | **857,016** | 0.92× |
| 40 m | **387,622** | 0.41× |
| 80 m | **193,730** | 0.21× |

**20 m is 8% cheaper than 10 m, not 90%.** The honest choice is therefore 10 m (same cost as 20 m,
four times the pixels) or 40 m (2.4× cheaper, still ~2.5 px across a 100 m corridor). The sampler
defaults to 40 m and takes `resolution=10` for the fidelity run.

Two traps found while measuring, both of which silently inflate the bill:

1. **A small window at the first overview level made GDAL stream the entire 172 MB file.** Reading
   the full 8 km tile costs 857 KB; reading a 2 km window of the same level cost 172 MB, twice.
   The sampler therefore always reads whole tiles.
2. **A `HEAD` response with `Content-Length: 0` makes GDAL abandon range requests** and download
   whole files. That was a defect in the measuring proxy, and it cost 172 MB to notice.

---

## F17 — Phase 3 pilot: measured cost, and a problem with the index

Run 2026-10-29 by `scripts/sample_pilot.py` on **Lagos** — the best-labelled state, 200 corridors
crossing it — at 40 m over the three most recent available months.

Run twice, because the first number looked too good. Both runs sampled the same 5 tiles over the
same 3 months (2026-05..07). Run 2 had five tile-months skip because STAC listed no item for that
tile-month; the sampler treats that as a skip, not a failure. Byte figures are per tile-month, so
the comparison holds.

| Metric | Run 1 | Run 2 |
|---|---:|---:|
| Tiles available in the state | 111 | 111 |
| Tile-months sampled | 15 | 10 |
| Rows written | 465 | 310 |
| Bytes downloaded | 9.7 MB | 7.4 MB |
| HTTP requests | 90 | 62 |
| **Bytes per tile-month (3 bands)** | **646 KB** | **744 KB** |
| **Seconds per tile-month** | **10.7** | **30.5** |
| National 24-month projection | 31.3 GB | 36.0 GB |
| Serial runtime projection | 143 h | 410 h |

**Bytes are reproducible within ±15%; runtime is not** — a 3× spread driven by network and CPU
contention. Quote bytes for cost, and treat runtime as an order-of-magnitude (tens to hundreds of
hours), not a schedule.

Combined with F16 and the 2,016 national tiles from F18, the full backfill is **~31–36 GB at 40 m**,
roughly **~70 GB at 10 m** — the same order as the original 40 GB estimate, and far above the 13 GB
that the mistaken 92 KB figure implied.

**Runtime, not bytes, is the real constraint.** Even the optimistic 143 h serial means the backfill
must be sharded; at 16 concurrent workers it is 9–26 hours. That is the number to design the
Phase 3→4 boundary around, and it is why the sampler reads one tile and masks every corridor in it
rather than looping per corridor.

### The index problem: a road centreline is asphalt, not vegetation

Mean NDVI on the sampled corridors came back at or below zero — `Lekki - Ikoyi Bridge` −0.081,
`Allen Avenue` −0.000, while NDBI sat around 0.15–0.18 everywhere. That is not a bug; it is the
index measuring tarmac.

A 40 m pixel centred on a carriageway is mostly sealed surface, so NDVI ≈ 0 whether the road is
pristine or disintegrating. **Centreline NDVI cannot detect road degradation.** The signal has to
come from the contrast between the road and its immediate surroundings: a maintained corridor has
tidy verges and drainage, a failing one has encroaching dust, bare laterite and vegetation loss at
its edges.

The fix for Phase 4 is to sample **two rings per corridor** — an inner centreline band and an outer
band 50–150 m off the centreline — and use their difference and ratio as features. This is a design
change, not a tuning parameter, and it is recorded here rather than discovered again later.

---

## F18 — National imagery coverage: 2,016 tiles, not 6,000

Computed 2026-10-29 by `scripts/count_tiles.py` from the corridor geometry, with no imagery
fetched. This closes O2.

| Metric | Value |
|---|---:|
| Corridors with geometry | 869 (850 after F20) |
| **Distinct 8 km tiles containing highway** | **2,016** |
| Distinct 96 km items | 97 |
| Median tiles per corridor | 2 |
| Max tiles per corridor | 83 |
| Occupancy of the network's bounding box | 9.9% |

The 6,000-tile estimate was ~3× high, and the 90–110 item estimate was right. The occupancy figure
is the interesting one: the federal network fills under a tenth of the box it spans, which is why
tile-counting rather than bbox-area arithmetic is the only honest way to size the job.

---

## F19 — The contrast feature works, but only at 10 m

Measured 2026-10-29 via `scripts/ablate_resolution.py` (3 tiles, 3 months, Lagos, 306 corridor-month
pairs) after fixing a design defect described below.

| Metric | Value | Threshold | Result |
|---|---:|---:|---|
| Level rank correlation (10 m vs 40 m) | 0.937 | ≥ 0.80 | ✅ |
| Change rank correlation | 0.917 | ≥ 0.60 | ✅ |
| Contrast rank correlation | 0.793 | ≥ 0.60 | ✅ |
| **Contrast sign agreement** | **79.4%** | ≥ 80% | ❌ |
| Mean absolute NDVI gap | 0.0355 | — | — |
| Bias (40 m − 10 m) | +0.0307 | — | — |

**Verdict: 40 m is fine for a level index and for month-to-month change, but not for the contrast
feature.** One corridor-month in five flips the sign of `verge − core` between resolutions — and
the sign is the whole point of that feature. The condition signal has to run at 10 m.

That reverses the cost recommendation for Phase 4 while leaving O3's original answer intact: the
question was never really "which resolution is cheapest" but "which resolution preserves what".
40 m preserves the landscape index (31 GB). 10 m is needed for the road signal (~70 GB).

### A measurement artefact worth recording

The first implementation of the two-band design dilated the centreline into a 50 m "inner band"
and called that the road. At 40 m, 50 m of dilation is **one pixel**, so the "road" band already
spanned ±40 m and sampled the verge it was supposed to be compared against. The result was a
contrast that came back **negative on every corridor** (−0.17 to −0.07) and looked like a
discovery about Lagos.

It was an artefact. With an undilated centreline the same tiles give positive contrast on most
corridors (+0.008 to +0.023 at 10 m), with carriageway NDVI of 0.03–0.12 — asphalt, as expected.

The lesson generalises: at a 40 m pixel, **any** band narrower than ~80 m cannot be separated from
its surroundings. Dilating a mask is not free geometry; it changes what the mask means.

---

## F20 — 869 names are 850 corridors, and the duplicate key broke the first real merge

Measured 2026-10-30 on the first real backfill run (workflow run 41135798985: 2 months at 10 m,
96 shards). All 96 shards sampled cleanly — 6,324 rows across 2,016 tiles, zero failures — and
then the merge job **failed** with `shards overlap; check the strided split` over **32 duplicate
`(corridor_id, tile_x, tile_y, month)` rows**.

The shards were not overlapping. `corridors.csv` held **869 rows over 850 distinct
`corridor_id`s**: 18 slugs were used more than once, every one of them a case/punctuation variant
of a single road.

| slug | spellings (segments) |
|---|---|
| `airport-road` | Airport Road (321) · Airport road (6) · AIRPORT ROAD (6) |
| `benin-sagamu-expressway` | Benin-Sagamu Expressway (336) · Benin - Sagamu Expressway (53) |
| `wudil-potiskum-federal-road` | Wudil - Potiskum Federal Road (457) · wudil potiskum Federal Road (2) |
| 15 others | `ahmadu-bello-way`, `east-west-road`, `lagos-badagry-expressway`, … |

**Why this is worse than one failed job:** `corridor_id` is the join key for every table
upstream and downstream, and it was not unique. A road spelled two ways became two ids, so its
imagery rows, its labels and its risk score would have been split between them. The merge gate
was the only thing that noticed.

**Fix:** group by slug, not by raw name. The spelling with the most segments (then the most
metres) supplies the display name; the others are kept in an `aliases` column so geometry and
label matches still join through them. `attach_labels` joins on the slug of `matched_name`, and
`geometry`/`backfill`/`count_tiles` resolve raw names through `corridors.alias_map`.

| Metric | Before | After |
|---|---:|---:|
| Corridor rows | 869 | **850** |
| Distinct `corridor_id` | 850 | **850** |
| Duplicate ids | 18 (37 rows) | **0** |
| Named length | 18,419.1 km | **18,419.1 km** |
| Median corridor length | 4.57 km | **4.65 km** |
| Corridors with a high-confidence label | 66 | **66** |
| Label events | 181 | **181** |
| Corridors with geometry | 869/869 | **850/850** |
| GeoJSON | 2.74 MB | **2.73 MB** |

Length, labels and coverage are unchanged, which is the check that this merged spellings of one
road rather than absorbing different roads into each other.

**The gate behaved correctly.** It refused to publish a table whose key was not unique, and it
failed loudly. The fix belongs in the key, not in the check.

**Also found, unfixed:** the workflow uploads `data/features/backfill_state_r*.json`, but
`scripts/backfill.py` writes its state file as `imagery_r{res}_shardNNofMM.json`. The glob never
matches, so the per-shard state (tiles, months, seconds, rows) is silently dropped from every
artifact. Nothing depends on it yet — it matters only once a shard is resumed across runs.

---

## F21 — The national backfill is ~1–3 hours, not 12–20

Measured 2026-10-30 from the first real run (workflow run 41135798985): 2 months at 10 m, 96
shards, 2,016 tiles.

| Metric | Measured |
|---|---|
| Shards | 96, zero failures |
| Wall clock, whole run including prepare and merge | **~20 min** |
| Per shard, including ~2 min install/setup | median **2.8 min**, range 2.4–5.2 |
| Per tile-month at 10 m | **~1–4 s** |
| Rows produced | 6,324 across 2,016 tiles |

The plan carried 10–30 s per tile-month, measured at 40 m from a workstation (F17), and projected
12–20 h. Two reasons the runner is much faster:

1. **The 40 m pilot was latency-bound, not bandwidth-bound.** An 8 km footprint at 40 m needs nine
   256 px overview tiles per band — 27 requests for three bands. At 10 m it needs one 800 px base
   tile per band — three requests (F16). Fewer round trips beat more pixels, which is why 10 m is
   *cheaper in wall clock* than 40 m even though it moves more bytes.
2. Shards run concurrently on a runner with a better path to `af-south-1` than a home connection.

Extrapolated to the full 22-month default: 462 tile-months per shard at 1–4 s is 8–31 min, and
five waves over 96 shards is **~1–3 h wall clock**, ~70 GB streamed, nothing stored. That is a
projection from two measured months, not a measurement of the whole job.

**Consequences:** the 96-shard choice still holds (and is still what a cancelled job would want to
be), but the 6 h job limit no longer binds. A 2-month session at ~20 min is now a convenience for
someone with an evening, not a necessity.

---

## F10 — Findings that are still open

| # | Open question | How it gets closed |
|---|---|---|
| O1 | ~~What fraction of the 3,233 labels match a named segment at high confidence?~~ | **Closed** — 181/1,672 high-confidence, 66 corridors (F11) |
| O2 | ~~How many distinct 8 km tiles actually contain highway?~~ | **Closed** — 2,016 tiles across 97 items (F18) |
| O3 | ~~Does 40 m NDVI rank corridors the same as 10 m?~~ | **Closed** — levels ρ=0.937, change ρ=0.917, contrast ρ=0.793 but sign agreement 79.4% (F19) |
| O6 | ~~Does a road-minus-verge contrast beat centreline NDVI?~~ | **Closed** — it is measurable and signed correctly at 10 m; whether it predicts condition needs labels (F19) |
| O4 | Are the 2024-heavy labels a budget artefact or a genuine deterioration signal? | Year fixed effects + a stated limitation; cannot be fully resolved |
| O5 | Does Hugging Face Datasets serve Parquet efficiently enough for DuckDB `httpfs`? | **Partly closed** — anonymous range reads return 206 (F15); throughput still to be measured once a real file is uploaded |
