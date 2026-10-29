"""Package the derived tables and publish them to Hugging Face Datasets.

Usage:
    python scripts/publish_dataset.py            # build dist/dataset, do not upload
    python scripts/publish_dataset.py --upload   # build and push (needs HF_TOKEN)

Reads:  data/interim/{corridors,events,label_matches}.csv
Writes: dist/dataset/*.parquet, dist/dataset/README.md  (the dataset card)

Default is build-only on purpose: uploading is irreversible in the sense that the repo is
public, so it should be an explicit flag rather than a side effect of running a script.
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from roadsense import config, hf  # noqa: E402

OUT_DIR = config.DIST / "dataset"

COLUMN_NOTES: dict[str, dict[str, str]] = {
    "corridors": {
        "corridor_id": "Stable slug derived from the corridor name; safe as a join key.",
        "name": "Corridor name exactly as GRID3 spells it, e.g. 'ABUJA-KADUNA ROAD'.",
        "n_segments": "GRID3 highway segments merged into this corridor.",
        "length_km": "Summed segment length. GRID3's own Shape__Length, not a geodesic recompute.",
        "states": "Pipe-separated states the corridor crosses. Long corridors cross several.",
        "primary_state": "State with the most segments — a display convenience, not a truth.",
        "primary_class": "Most common GRID3 class: motorway, trunk, primary or secondary.",
        "lon": "Mean segment centroid longitude, WGS84.",
        "lat": "Mean segment centroid latitude, WGS84.",
        "label_events": "High-confidence procurement interventions matched to this corridor.",
        "label_years": "Years those interventions occurred, pipe-separated.",
    },
    "events": {
        "ocid": "Open Contracting ID from the Nigeria OCDS publication (NOCOPO/BPP).",
        "date": "Award or contract date as published.",
        "buyer": "Procuring entity, filtered to FERMA and the Federal Ministry of Works.",
        "text": "Project title as published. Source of the road phrase and state.",
        "amount": "Budget amount in naira, as published. Budgeted, not audited actual spend.",
        "tender_amount": "Tender value where present. Only ~21% of rows carry one.",
        "intervention": "Classifier output: maintenance, rehabilitation, construction, or other.",
        "state": "State named in the text, normalised; empty when no state was named.",
        "road_phrase": "The road name extracted from the title before matching.",
        "year": "Calendar year of the event.",
    },
    "label_matches": {
        "ocid": "Open Contracting ID of the event.",
        "year": "Event year.",
        "state": "State used for matching.",
        "road_phrase": "Road name extracted from the event title.",
        "amount": "Event budget amount in naira.",
        "segment_id": "GRID3 segment id of the matched representative segment.",
        "matched_name": "GRID3 corridor name the phrase was matched to.",
        "matched_class": "GRID3 road class of the match.",
        "score": "Token-overlap score in [0, 1] used to rank candidates.",
        "shared_tokens": "Number of place tokens in common.",
        "exact_anchor": "Whether an anchor token matched exactly.",
        "confidence": "high, medium or low. Only 'high' is used as a training label.",
        "candidates": "Plausible corridors considered for this event.",
        "rule": "Which matching rule fired; empty when nothing matched.",
    },
}

CARD_TEMPLATE = """---
license: cc-by-sa-4.0
language:
  - en
tags:
  - roads
  - nigeria
  - remote-sensing
  - infrastructure
  - geospatial
pretty_name: RoadSense Nigeria — federal road corridors
---

# RoadSense Nigeria — federal road corridors

Derived tables for a road-degradation and maintenance-allocation study of Nigeria's federal
highway network. **This is a derived dataset, not a mirror of the sources**: every file here is
the output of the code in the [RoadSense repository]({repo_url}), and the sources remain the
authoritative copies.

## Files

| File | Rows | What it is |
|---|---|---|
| `corridors.parquet` | {n_corridors:,} | The modelling unit: one row per named corridor |
| `events.parquet` | {n_events:,} | Road intervention records from Nigerian public procurement |
| `label_matches.parquet` | {n_matches:,} | Event-to-corridor matching, every confidence band |

## Load it

```python
import pandas as pd

BASE = "https://huggingface.co/datasets/{repo}/resolve/main"
corridors = pd.read_parquet(f"{{BASE}}/corridors.parquet")
events = pd.read_parquet(f"{{BASE}}/events.parquet")
```

No token and no Hugging Face account are needed — these are public files served over HTTPS.

## What is unusual about this dataset

Three properties will surprise anyone expecting a tidy supervised-learning table. They are
stated here rather than buried, because a model built on this data is only defensible if the
reader knows them.

**1. Labels are interventions, not failures.** A procurement record means money was allocated to
a road. It does not mean the road failed, and its absence does not mean the road is intact. Any
target derived from `label_matches.parquet` is a proxy for *intervention need*, not for physical
degradation.

**2. The labelled subset is small.** {n_corridors:,} corridors exist; **{n_labelled}** carry at
least one high-confidence event, and **{n_repeat}** carry more than one. This is why the project
publishes a satellite degradation index across all corridors and treats the labelled subset as an
external validation check rather than a training set. See the repository's
`docs/label-matching-report.md` for the matching method and its measured ceiling.

**3. The record has a hole in 2022.** Events by year: {year_counts}. There are no 2022 records and
only partial 2026 coverage, so a temporal split must skip the gap rather than interpolate across
it.

## Provenance

- **Road geometry** — GRID3 NGA Roads v1.0 (CIESIN, Columbia University), CC BY-SA 4.0.
  {n_segments:,} named highway segments aggregated to {n_corridors:,} corridors.
- **Interventions** — Nigeria OCDS, Bureau of Public Procurement / NOCOPO, published via the
  Open Contracting Data Standard registry. Filtered to FERMA and Federal Ministry of Works road
  projects.
- **Admin boundaries** — geoBoundaries `gbOpen` NGA ADM1, itself GRID3-derived.
- **Imagery** (later phases) — Digital Earth Africa Sentinel-2 Rolling Monthly GeoMAD.

Retrieved 2026-10-28. The repository's `data/raw/manifest.json` records exact source URLs and
timestamps for each build.

## Licence

Data is released under **CC BY-SA 4.0**, inherited from GRID3. Code that produces it is MIT.
If you use this dataset, attribute GRID3 and the Bureau of Public Procurement.

## Caveats worth repeating

- `length_km` sums GRID3's own length attribute; it is not a fresh geodesic measurement.
- `amount` is a budget figure. It is not audited expenditure and should not be read as cost.
- Corridor names are inherited spelling from GRID3 and are not normalised to any official
  gazetteer. Two spellings of one road would appear as two corridors.
- State assignment is by centroid. Corridors that cross a state line carry every state they
  cross in `states`, and the first-entry `primary_state` is a display convenience only.
"""


def _year_counts(events: pd.DataFrame) -> str:
    counts = events["year"].dropna().astype(int).value_counts().sort_index()
    return ", ".join(f"{year}: {count:,}" for year, count in counts.items())


def build(out_dir: Path) -> dict:
    """Convert the interim tables to parquet and write the dataset card."""
    out_dir.mkdir(parents=True, exist_ok=True)
    tables: dict[str, pd.DataFrame] = {}

    for name, filename in config.PUBLISHED_TABLES.items():
        source = config.DATA_INTERIM / f"{name}.csv"
        if not source.exists():
            raise FileNotFoundError(f"missing {source}; run the pipeline before publishing")
        frame = pd.read_csv(source)
        frame.to_parquet(out_dir / filename, index=False)
        tables[name] = frame

    corridors = tables["corridors"]
    card = CARD_TEMPLATE.format(
        repo=config.HF_DATASET_REPO,
        repo_url="https://github.com/batestguy/roadsense-nigeria",
        n_corridors=len(corridors),
        n_events=len(tables["events"]),
        n_matches=len(tables["label_matches"]),
        n_labelled=int((corridors["label_events"] > 0).sum()),
        n_repeat=int((corridors["label_events"] > 1).sum()),
        n_segments=int(corridors["n_segments"].sum()),
        year_counts=_year_counts(tables["events"]),
    )
    (out_dir / "README.md").write_text(card, encoding="utf-8")
    return tables


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--upload", action="store_true", help="push to Hugging Face")
    parser.add_argument("--repo", default=config.HF_DATASET_REPO)
    args = parser.parse_args()

    tables = build(OUT_DIR)

    print("[publish] packaged")
    for name, frame in tables.items():
        path = OUT_DIR / config.PUBLISHED_TABLES[name]
        print(f"  {path.name:26s} {len(frame):>7,} rows  {path.stat().st_size / 1024:8.1f} KB")
    print(f"  {'README.md':26s} {'':>7}       (dataset card)")

    if not args.upload:
        print(f"\n[publish] built {OUT_DIR.relative_to(config.ROOT)} — pass --upload to push")
        return 0

    url = hf.publish(OUT_DIR, repo_id=args.repo)
    print(f"\n[publish] uploaded to {url}")
    for filename in config.PUBLISHED_TABLES.values():
        print(f"  {hf.resolve_url(filename, repo_id=args.repo)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
