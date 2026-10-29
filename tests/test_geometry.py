from __future__ import annotations

import json

import pandas as pd

from roadsense import geometry


def test_simplify_keeps_endpoints_and_drops_collinear_vertex():
    points = [[0.0, 0.0], [0.5, 0.0], [1.0, 0.0]]
    assert geometry.simplify(points, 0.0001) == [[0.0, 0.0], [1.0, 0.0]]


def test_simplify_keeps_a_vertex_that_carries_the_shape():
    points = [[0.0, 0.0], [0.5, 0.01], [1.0, 0.0]]
    assert len(geometry.simplify(points, 0.0001)) == 3


def test_simplify_is_a_no_op_for_short_paths():
    points = [[0.0, 0.0], [1.0, 1.0]]
    assert geometry.simplify(points, 0.0001) == points


def test_simplify_preserves_direction_and_order():
    points = [[3.0, 0.0], [2.0, 0.0], [1.0, 0.0], [0.0, 0.0]]
    assert geometry.simplify(points, 0.0001) == [[3.0, 0.0], [0.0, 0.0]]


def test_perpendicular_distance_measures_offset_from_the_segment():
    assert abs(geometry.perpendicular_distance([0.5, 0.5], [0.0, 0.0], [1.0, 0.0]) - 0.5) < 1e-9


def test_perpendicular_distance_handles_a_degenerate_segment():
    assert geometry.perpendicular_distance([3.0, 4.0], [0.0, 0.0], [0.0, 0.0]) == 5.0


def test_simplify_all_drops_paths_that_collapse():
    paths = [[[0.0, 0.0], [1.0, 0.0]], [[2.0, 0.0], [2.0, 0.0]]]
    assert len(geometry.simplify_all(paths, 0.0001)) == 2
    assert len(geometry.simplify_all(paths, 0.0)) == 2


def _corridors() -> pd.DataFrame:
    return pd.DataFrame(
        [
            {
                "corridor_id": "a-b-road",
                "name": "A B ROAD",
                "n_segments": 3,
                "length_km": 12.5,
                "states": "Kano|Kaduna",
                "primary_state": "Kano",
                "primary_class": "trunk",
                "lon": 8.0,
                "lat": 11.0,
                "label_events": 2,
                "label_years": "2024|2025",
            },
            {
                "corridor_id": "ghost-road",
                "name": "GHOST ROAD",
                "n_segments": 1,
                "length_km": 1.0,
                "states": "Oyo",
                "primary_state": "Oyo",
                "primary_class": "primary",
                "lon": 3.0,
                "lat": 8.0,
                "label_events": 0,
                "label_years": "",
            },
        ]
    )


def test_build_feature_collection_joins_paths_to_the_table():
    paths = {"A B ROAD": [[[7.0, 10.0], [7.5, 10.5], [8.0, 11.0]]]}
    fc = geometry.build_feature_collection(_corridors(), paths, tolerance=0.0)

    assert len(fc["features"]) == 1
    feature = fc["features"][0]
    assert feature["id"] == "a-b-road"
    assert feature["geometry"]["type"] == "MultiLineString"
    assert feature["properties"]["primary_state"] == "Kano"
    assert feature["properties"]["label_events"] == 2
    assert feature["properties"]["n_parts"] == 1
    assert fc["missing"] == ["GHOST ROAD"]


def test_build_feature_collection_records_bbox():
    paths = {"A B ROAD": [[[7.0, 10.0], [8.5, 11.25]]]}
    fc = geometry.build_feature_collection(_corridors(), paths, tolerance=0.0)
    assert fc["features"][0]["properties"]["bbox"] == [7.0, 10.0, 8.5, 11.25]


def test_build_feature_collection_skips_empty_path_lists():
    fc = geometry.build_feature_collection(_corridors(), {"A B ROAD": []}, tolerance=0.0)
    assert fc["features"] == []
    assert set(fc["missing"]) == {"A B ROAD", "GHOST ROAD"}


def test_write_feature_collection_omits_internal_keys(tmp_path):
    paths = {"A B ROAD": [[[7.0, 10.0], [8.0, 11.0]]]}
    fc = geometry.build_feature_collection(_corridors(), paths, tolerance=0.0)
    dest = geometry.write_feature_collection(fc, tmp_path / "out.geojson")

    payload = json.loads(dest.read_text(encoding="utf-8"))
    assert payload["type"] == "FeatureCollection"
    assert "missing" not in payload
    assert "total_vertices" not in payload
    assert len(payload["features"]) == 1


def test_coordinates_are_rounded_to_five_places(tmp_path):
    paths = {"A B ROAD": [[[7.123456789, 10.987654321], [8.0, 11.0]]]}
    fc = geometry.build_feature_collection(_corridors(), paths, tolerance=0.0)
    coords = fc["features"][0]["geometry"]["coordinates"][0]
    assert coords[0] == [7.12346, 10.98765]
