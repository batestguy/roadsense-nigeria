---
license: cc-by-sa-4.0
language:
  - en
tags:
  - roads
  - nigeria
  - remote-sensing
  - infrastructure
  - geospatial
  - sentinel-2
pretty_name: RoadSense Nigeria — corridor imagery, condition and weather
task_categories:
  - tabular-regression
---

# RoadSense Nigeria — corridor imagery, condition and weather

Monthly satellite observations and derived condition measures for 850 named federal road
corridors in Nigeria, over 22 months (2024-09 to 2026-06), joined to monthly reanalysis
weather by corridor. Every file is an output of the RoadSense pipeline and can be rebuilt
from the sources listed below; this dataset is a snapshot, not a mirror of them.

> **Commercial use of the weather files is not permitted.** The rainfall and soil-moisture
> columns come from Open-Meteo's free tier, which is licensed for non-commercial use only.
> See [Licence](#licence) before you use this dataset for anything paid.

## 1. The negative result — read this first

The question this dataset was built to answer is: *does road-versus-verge spectral contrast
separate corridors that received maintenance from those that did not?*

**It does not. The test failed.** The primary score (year-over-year change in NDVI contrast)
ranked the 66 procurement-labelled corridors against 578 matched unlabelled ones at
**AUC 0.3901** — 95% bootstrap CI 0.3196–0.4671 — against a pre-committed bar of **0.60**.
Both the point estimate and its lower bound miss the bar; the estimate is *below* 0.5, so on
this evidence the score is worse than a coin flip at ranking intervention need. A permutation
null on the same design has a median AUC of 0.4907, which is where an uninformative score sits.

Three further results point the same way, and are reported here rather than left in the repo:

- The raw contrast level did no better (matched AUC 0.3133).
- A secondary instrument (OLS slope of contrast over time) also failed: AUC 0.4318 (CI 0.3544–0.5137).
- The alternative anomaly definition from the earlier ticket reached AUC 0.5735 with an
  unmatched set, and 0.4789 when balanced within 13 class-and-length cells.

What the dataset *does* support is measurement: 18,517 corridor-months of usable contrast,
anomalies that survive variance decomposition (81.5% of NDVI contrast variance is between
corridors, 5.8% between months, 12.8% residual), and weather covariates with no imputed days.
What it does not support is a claim that these columns predict maintenance need. Treat
`label_events` as a record that money was allocated, not that a road failed.

## 2. Provenance

| Item | Source | Access date (UTC) | Notes |
|---|---|---|---|
| Imagery bands | Digital Earth Africa Sentinel-2 Rolling Monthly GeoMAD, collection `gm_s2_rolling` via the DE Africa STAC API | 2026-10-30 to 2026-11-09 | 10 m resolution. 22 monthly mosaics per corridor; read through STAC search + COG range requests. Each row carries the STAC `item_id` it came from. |
| Rainfall, soil moisture | Open-Meteo Historical Weather API (archive), ERA5 / ERA5-Land reanalysis | 2026-11-09 07:57 | 82 one-degree cells, daily values summed/meaned to months, path-length-weighted per corridor. |
| Daily rainfall features | Same, plus a 2024-08 lookback fetch for trailing windows | 2026-11-09 09:10 | Rolling 30-day and 7-day windows, dry-spell counts. |
| Corridor network | GRID3 NGA Roads v1.0 (CIESIN, Columbia University) | 2026-10-28 | DOI 10.7916/b42r-6w17. Named highway segments merged into 850 corridors. |

### Backfill runs behind `imagery_r10.parquet`

Each 2-month window was one GitHub Actions run; `imagery_r10.manifest.json` records the
concatenation. GitHub artefact retention is 90 days, so these expire on the dates shown.

| Run id | Months | Run started (UTC) | Artefact expires |
|---|---|---|---|
| 41140244419 | 2024-09 … 2024-10 | 2026-10-30 22:45 | 2027-01-28 |
| 41142676535 | 2024-11 … 2024-12 | 2026-10-30 23:08 | 2027-01-28 |
| 41144644682 | 2025-01 … 2025-02 | 2026-10-30 23:28 | 2027-01-28 |
| 41146408420 | 2025-03 … 2025-04 | 2026-10-30 23:46 | 2027-01-28 |
| 41148108390 | 2025-05 … 2025-06 | 2026-10-31 00:04 | 2027-01-29 |
| 42474933427 | 2025-07 … 2025-08 | 2026-11-08 11:15 | 2027-02-06 |
| 42476457890 | 2025-09 … 2025-10 | 2026-11-08 11:35 | 2027-02-06 |
| 42577550324 | 2025-11 … 2025-12 | 2026-11-09 07:09 | 2027-02-07 |
| 42579676085 | 2026-01 … 2026-02 | 2026-11-09 07:29 | 2027-02-07 |
| 42581613539 | 2026-03 … 2026-04 | 2026-11-09 07:48 | 2027-02-07 |
| 42586944075 | 2026-05 … 2026-06 | 2026-11-09 08:34 | 2027-02-07 |

Because the run artefacts expire, `imagery_r10.parquet` in this repository is the durable
copy of that work. The 22 months are complete: no month missing, no duplicate
`(corridor_id, tile_x, tile_y, month)` key, 850 corridors per month.

## 3. Schema

Every file joins on `corridor_id`; the imagery file keys on
`(corridor_id, tile_x, tile_y, month)`.

### `imagery_r10.parquet` — 69,212 rows × 15 columns

One row per corridor × 8 km STAC tile × month.

| Column | Type | Meaning |
|---|---|---|
| `corridor_id` | string | Stable slug derived from the corridor name; join key everywhere. |
| `corridor_name` | string | Corridor name as GRID3 spells it. |
| `tile_x`, `tile_y` | int | DE Africa STAC tile grid indices for the 8 km tile read. |
| `month` | string | `YYYY-MM`, the mosaic month. |
| `resolution_m` | int | Always 10 (the 40 m control was not published). |
| `item_id` | string | STAC item UUID of the GeoMAD mosaic actually read. |
| `pixels_core` | int | 10 m pixels in the road band (the carriageway buffer). |
| `pixels_ring` | int | 10 m pixels in the surrounding verge ring. |
| `ndvi_core`, `ndvi_ring` | float | Mean NDVI in the road band and in the verge ring. |
| `ndvi_contrast` | float | `ndvi_core - ndvi_ring`. Negative means the verge is greener than the road. |
| `ndbi_core`, `ndbi_ring` | float | Mean NDBI (built-up index) in the two bands. |
| `ndbi_contrast` | float | `ndbi_core - ndbi_ring`; positive means more built surface on the road. |

### `condition.parquet` — 18,700 rows × 30 columns

One row per corridor × month (850 × 22), unweighted band means aggregated up from tiles.

| Column | Type | Meaning |
|---|---|---|
| `corridor_id`, `corridor_name`, `month` | string | Keys. 18,700 = complete rectangle. |
| `ndvi_contrast`, `ndbi_contrast` | float | Primary measure: road-length-weighted mean of the per-tile contrasts (weight `pixels_core`). |
| `ndvi_contrast_unweighted`, `ndbi_contrast_unweighted` | float | Plain mean over the corridor's tiles. |
| `ndvi_contrast_pooled`, `ndbi_contrast_pooled` | float | Ring minus core after pooling both bands across tiles, instead of averaging ratios of tiles. |
| `ndvi_core`, `ndvi_ring`, `ndbi_core`, `ndbi_ring` | float | Corridor-level band means. |
| `ndvi_anom`, `ndbi_anom` | float | Within-month anomaly: value minus the median across corridors for that month. Removes the national seasonal swing. |
| `ndvi_anom2`, `ndbi_anom2` | float | Two-way anomaly: value − corridor mean − month mean + grand mean. Removes the corridor's own level (land cover, terrain, surface) as well as the monthly swing, from 16–22 observations. |
| `ndvi_yoy`, `ndbi_yoy` | float | Same calendar month one year earlier, differenced. Null where the earlier month does not exist; never imputed. |
| `ndvi_month_median`, `ndvi_month_mean`, `ndbi_month_median`, `ndbi_month_mean` | float | The national per-month statistics used to build `anom`; carried so the arithmetic can be checked. |
| `ndvi_corridor_mean`, `ndbi_corridor_mean` | float | The corridor's own 22-month level, used to build `anom2`. |
| `n_tiles`, `n_tiles_usable`, `n_tiles_usable_ndbi` | int | Tiles covering the corridor, and how many yielded a usable NDVI / NDBI read. |
| `pixels_core`, `pixels_ring` | int | Total pixels behind the corridor-month. |

### `weather.parquet` — 18,700 rows × 9 columns

| Column | Type | Meaning |
|---|---|---|
| `corridor_id`, `month` | string | Keys. |
| `precip_mm` | float | Rainfall total for the month, mm. |
| `soil_moisture_mean` | float | Mean volumetric soil moisture, m³/m³, top 0–7 cm. |
| `n_cells`, `n_cells_total` | int | One-degree cells used, and cells the centreline touches. |
| `days_present`, `days_expected` | int | Days with a value, and calendar days in the month. No filling. |
| `complete` | bool | `days_present == days_expected` for every contributing cell. |

### `weather_daily_features.parquet` — 18,700 rows × 13 columns

Trailing-window features. A window ending on day *d* covers *d−(n−1) … d*.

| Column | Type | Meaning |
|---|---|---|
| `corridor_id`, `month` | string | Keys. |
| `rain_mean_trailing30` | float | Mean, over the days of the month, of the trailing 30-day rainfall total — an average of rolling sums, not a cumulative total. |
| `rain_cum_30d` | float | Rainfall total over the trailing 30 days ending on the last day of the month. |
| `rain_max_7d` | float | Largest trailing 7-day rainfall total within the month. |
| `dry_spell_days` | float | Days in the month with no rain in a stretch of consecutive dry days. |
| `rain_mean_trailing30_days`, `rain_cum_30d_days`, `rain_max_7d_days`, `dry_spell_days_days` | float | Days of data behind each feature; the denominator, so the reader can see it. |
| `n_cells`, `n_cells_total` | int | Cells contributing, and cells touched. |
| `full_lookback_30d` | bool | Whether the trailing window had its full 30 days of data. All 18,700 rows are true. |

### `corridors.csv` — 850 rows × 12 columns

| Column | Type | Meaning |
|---|---|---|
| `corridor_id` | string | Stable slug; join key. |
| `name` | string | Corridor name as GRID3 spells it. |
| `aliases` | string | Alternative spellings merged into this corridor, pipe-separated. Mostly empty. |
| `n_segments` | int | GRID3 highway segments merged into the corridor. |
| `length_km` | float | Sum of GRID3's own length attribute, not a fresh geodesic measurement. |
| `states`, `primary_state` | string | States the corridor crosses, and the one with most segments (a display convenience). |
| `primary_class` | string | Most common GRID3 class: motorway, trunk, primary or secondary. |
| `lon`, `lat` | float | Mean segment centroid, WGS84. |
| `label_events` | int | Procurement records matched to this corridor at high confidence. A record that money was allocated, not that the road failed. |
| `label_years` | string | Years of those records, pipe-separated. |

### Manifests

`imagery_r10.manifest.json`, `condition.manifest.json`, `weather_manifest.json`,
`weather_daily_manifest.json` carry the run identifiers, source URLs, output SHA-256,
row and coverage counts, quality gates and the null inventory behind every figure quoted
above. Read them before trusting a number.

## 4. Known gaps — named, not buried

- **378 of 69,212 imagery rows (0.55%) have a blank contrast value** — in `ndvi_contrast`
  and `ndbi_contrast` alike. These are tile-months where the core or ring band had no usable
  pixels. They are not zeros and must not be read as "no contrast".
- **183 corridor-months (1.0% of 18,700) have no usable reading, spread over 124 corridors.**
  36 corridors are missing in more than one month, the worst missing 7 of 22. The list is
  reproducible from `condition.parquet`; the build also wrote it as `condition.nulls.csv`, which
  is not published here. 91 of the 183 fall in 2025-07 (cloud cover in the rolling mosaic).
- **June 2026 year-on-year is available for 805 of 850 corridors.** A year-on-year value needs
  usable reads in both June 2025 and June 2026; 45 corridors lack one. The other nine YoY pairs
  cover 845–850 corridors each.
- **`ndvi_yoy` / `ndbi_yoy` are null in 10,263 of 18,700 rows** by construction: 22 months give
  only 10 complete annual pairs, so the first 12 months have no predecessor.
- Corridor names are GRID3 spellings, not normalised to an official gazetteer. Two spellings of
  one road would appear as two corridors; 18 corridors absorbed an alternative spelling, which is
  recorded in `aliases`.
- State assignment is by centroid. A corridor crossing a state line carries every state it
  crosses.
- Road bands were sampled from GRID3 centreline geometry, so a corridor that was rebuilt on a
  new alignment after 2024 is measured where the old road is.

## 5. Licence

**Code** in the RoadSense repository is MIT.

**Derived data here is CC BY-SA 4.0**, inherited from GRID3 NGA Roads v1.0:
attribution plus share-alike. If you redistribute this dataset or a derivative, you must credit
the sources below and license your redistribution the same way.

**The weather columns are non-commercial only.** Rainfall and soil-moisture values come from
Open-Meteo's free tier (ERA5 / ERA5-Land reanalysis, CC BY 4.0), whose terms permit
**non-commercial use only**. Any commercial use of this dataset requires a paid Open-Meteo
subscription and a fresh look at the share-alike obligations. This dataset as published is a
research artefact and is offered on that basis.

Attribution required:

1. **GRID3 NGA Roads v1.0** — Center for Integrated Earth System Information (CIESIN),
   Columbia University, 2025. DOI [10.7916/b42r-6w17](https://doi.org/10.7916/b42r-6w17). CC BY-SA 4.0.
2. **Sentinel-2 Rolling Monthly GeoMAD** — Digital Earth Africa. Contains modified Copernicus
   Sentinel data.
3. **Copernicus Sentinel-2** — European Space Agency / European Commission.
4. **Weather** — Open-Meteo.com (ERA5 reanalysis), CC BY 4.0, non-commercial.
5. **Procurement labels** — Nigeria Open Contracting Portal (NOCOPO), Bureau of Public
   Procurement, via the Open Contracting Data Standard registry.

## 6. Reproduce the headline number

```python
from huggingface_hub import hf_hub_download
import pandas as pd
path = hf_hub_download("JBZABC/roadsense-nigeria", "condition.parquet", repo_type="dataset")
print(pd.read_parquet(path).shape)  # (18700, 30)
```

No account, token or permission is needed — the files are public over HTTPS. Rebuilding
`condition.parquet` from imagery needs `scripts/build_condition.py` in the repository, and
re-running the failed validation needs `scripts/validate_signal_v2.py`; both take the published
files as input and no network.
