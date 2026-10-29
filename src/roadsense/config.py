"""Project-wide constants and paths.

Every external endpoint used by the pipeline is named here exactly once, so a source
changing its URL is a one-line fix rather than a hunt through modules.
"""

from __future__ import annotations

from pathlib import Path

# --- Paths -------------------------------------------------------------------

ROOT = Path(__file__).resolve().parents[2]
DATA_RAW = ROOT / "data" / "raw"
DATA_INTERIM = ROOT / "data" / "interim"
DIST = ROOT / "dist"
DOCS = ROOT / "docs"

# --- Published dataset -------------------------------------------------------

#: Hugging Face dataset repo holding the derived tables. Public, read anonymously.
#: Free tier, no payment method required (unlike Cloudflare R2 — see findings F5).
HF_DATASET_REPO = "roadsense-ng/nigeria-roads"
HF_DATASET_REVISION = "main"

#: Files published from ``data/interim``, and the parquet name each is written under.
PUBLISHED_TABLES: dict[str, str] = {
    "corridors": "corridors.parquet",
    "events": "events.parquet",
    "label_matches": "label_matches.parquet",
}

# --- Sources -----------------------------------------------------------------

# GRID3 NGA Roads v1.0 (CIESIN, Columbia University). CC BY-SA 4.0. Anonymous access.
GRID3_ROADS_URL = (
    "https://services3.arcgis.com/BU6Aadhn6tbBEdyk/arcgis/rest/services/"
    "GRID3_NGA_roads/FeatureServer/0"
)

# Nigeria OCDS (NOCOPO / Bureau of Public Procurement) via the OCDS data registry.
OCDS_CSV_URL = (
    "https://data.open-contracting.org/en/publication/64/download?name=full.csv.tar.gz"
)

# Admin-1 boundaries. geoBoundaries gbOpen, itself derived from GRID3 state boundaries.
ADM1_API_URL = "https://www.geoboundaries.org/api/current/gbOpen/NGA/ADM1/"

# Digital Earth Africa STAC. Sentinel-2 Rolling Monthly GeoMAD: 10 m, cloud-free, 2019-present,
# anonymous S3 range reads. See findings F2.
GEOMAD_STAC_URL = "https://explorer.digitalearth.africa/stac"
GEOMAD_COLLECTION = "gm_s2_rolling"

#: Nigeria bounding box (WGS84) used for STAC searches and coverage arithmetic.
NIGERIA_BBOX: tuple[float, float, float, float] = (2.6, 4.2, 14.8, 13.9)

# --- Domain constants --------------------------------------------------------

#: Road classes that constitute the federal highway network for this project.
#: Measured 2026-10-28: motorway 2,362 + trunk 38,074 + primary 56,262 + secondary 70,304.
HIGHWAY_CLASSES: tuple[str, ...] = ("motorway", "trunk", "primary", "secondary")

#: GRID3 caps a single query at 2000 features.
ARCGIS_PAGE_SIZE = 2000

#: Gate G0 thresholds, committed to in preflight-spec.md §5.
GATE_PROCEED = 800
GATE_CONDITIONAL = 300
