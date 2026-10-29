"""Tests for state-name extraction from procurement text."""

from __future__ import annotations

from roadsense.states import find_state, normalise_state_name


def test_finds_simple_state():
    assert find_state("MAINTENANCE OF ROAD IN BENUE STATE") == "Benue"


def test_abuja_maps_to_fct():
    assert find_state("CONSTRUCTION OF ACCESS ROAD, ABUJA") == "FCT"


def test_niger_delta_is_not_niger_state():
    assert find_state("ROAD PROJECT IN NIGER DELTA REGION") != "Niger"


def test_misspelled_nasarawa_is_recognised():
    assert find_state("ROAD IN NASARAWA STATE") == "Nasarawa"


def test_returns_none_when_no_state_present():
    assert find_state("SUPPLY OF TYRES") is None


def test_normalise_state_name_canonicalises_case():
    assert normalise_state_name("benue") == "Benue"
