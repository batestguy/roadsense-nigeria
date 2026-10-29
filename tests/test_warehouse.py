from __future__ import annotations

import pandas as pd
import pytest

from roadsense import config, warehouse

duckdb = pytest.importorskip("duckdb")


@pytest.fixture
def dataset_dir(tmp_path):
    base = tmp_path / "dataset"
    base.mkdir()
    pd.DataFrame(
        {
            "corridor_id": ["a-b-road", "c-d-road"],
            "name": ["A B ROAD", "C D ROAD"],
            "length_km": [10.0, 5.5],
            "label_events": [2, 0],
        }
    ).to_parquet(base / config.PUBLISHED_TABLES["corridors"], index=False)
    pd.DataFrame({"ocid": ["x", "y", "z"], "year": [2024, 2025, 2025]}).to_parquet(
        base / config.PUBLISHED_TABLES["events"], index=False
    )
    pd.DataFrame({"ocid": ["x", "y"], "confidence": ["high", "low"]}).to_parquet(
        base / config.PUBLISHED_TABLES["label_matches"], index=False
    )
    return base


def test_local_files_only_lists_what_exists(tmp_path):
    base = tmp_path / "dataset"
    base.mkdir()
    pd.DataFrame({"a": [1]}).to_parquet(base / config.PUBLISHED_TABLES["corridors"], index=False)
    assert set(warehouse.local_files(base)) == {"corridors"}


def test_connect_creates_one_view_per_table(dataset_dir):
    con = warehouse.connect(dataset_dir)
    names = {row[0] for row in con.execute("SHOW TABLES").fetchall()}
    assert names == {"corridors", "events", "label_matches"}


def test_summary_reports_the_built_counts(dataset_dir):
    con = warehouse.connect(dataset_dir)
    assert warehouse.summary(con) == {
        "corridors": 2,
        "corridors_with_labels": 1,
        "named_km": 15.5,
        "events": 3,
        "high_confidence_matches": 1,
    }


def test_views_are_queryable_with_sql(dataset_dir):
    con = warehouse.connect(dataset_dir)
    rows = con.execute(
        "SELECT name FROM corridors WHERE label_events > 0 ORDER BY name"
    ).fetchall()
    assert rows == [("A B ROAD",)]
