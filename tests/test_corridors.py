"""Tests for corridor aggregation."""

from __future__ import annotations

import pandas as pd

from roadsense.corridors import attach_labels, build_corridors, slugify, summarise


def _segments() -> pd.DataFrame:
    return pd.DataFrame(
        [
            {"segment_id": "a", "names": "Lagos-Ibadan Expressway", "road_class": "trunk",
             "length_m": 5000.0, "lon": 3.4, "lat": 6.6, "state": "Lagos"},
            {"segment_id": "b", "names": "Lagos-Ibadan Expressway", "road_class": "trunk",
             "length_m": 7000.0, "lon": 3.9, "lat": 7.0, "state": "Oyo"},
            {"segment_id": "c", "names": "Gwarzo Road", "road_class": "primary",
             "length_m": 2000.0, "lon": 8.1, "lat": 11.9, "state": "Kano"},
            {"segment_id": "d", "names": "", "road_class": "primary",
             "length_m": 1000.0, "lon": 8.2, "lat": 12.0, "state": "Kano"},
        ]
    )


def test_slugify_is_stable_and_url_safe():
    assert slugify("Enugu - Port Harcourt Expressway") == "enugu-port-harcourt-expressway"
    assert slugify("  Ajaokuta/Ayangba Road ") == "ajaokuta-ayangba-road"


def test_build_corridors_groups_by_name_and_drops_unnamed():
    table = build_corridors(_segments())
    assert len(table) == 2
    assert "unnamed" not in set(table["corridor_id"])

    ibadan = table.set_index("name").loc["Lagos-Ibadan Expressway"]
    assert ibadan["n_segments"] == 2
    assert ibadan["length_km"] == 12.0
    assert ibadan["states"] == "Lagos|Oyo"


def test_attach_labels_counts_high_confidence_only():
    table = build_corridors(_segments())
    matches = pd.DataFrame(
        [
            {"matched_name": "Lagos-Ibadan Expressway", "confidence": "high", "year": 2024},
            {"matched_name": "Lagos-Ibadan Expressway", "confidence": "high", "year": 2025},
            {"matched_name": "Gwarzo Road", "confidence": "medium", "year": 2024},
        ]
    )
    labelled = attach_labels(table, matches).set_index("name")

    assert labelled.loc["Lagos-Ibadan Expressway", "label_events"] == 2
    assert labelled.loc["Lagos-Ibadan Expressway", "label_years"] == "2024|2025"
    assert labelled.loc["Gwarzo Road", "label_events"] == 0


def test_summarise_reports_repeat_labelled_corridors():
    table = build_corridors(_segments())
    matches = pd.DataFrame(
        [
            {"matched_name": "Lagos-Ibadan Expressway", "confidence": "high", "year": 2024},
            {"matched_name": "Lagos-Ibadan Expressway", "confidence": "high", "year": 2025},
        ]
    )
    summary = summarise(attach_labels(table, matches))
    assert summary["corridors"] == 2
    assert summary["corridors_with_labels"] == 1
    assert summary["corridors_with_repeat_labels"] == 1
    assert summary["label_events_total"] == 2
