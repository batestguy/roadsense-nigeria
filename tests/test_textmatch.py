"""Tests for the road-name matching logic.

These encode the cases that actually appear in the Nigeria OCDS export, so a regression here
means a regression in label quality.
"""

from __future__ import annotations

from roadsense.textmatch import (
    distinctive_tokens,
    extract_phrases,
    normalise,
    score_match,
)


def test_normalise_strips_punctuation_and_collapses_space():
    assert normalise("KATSINA-DAURA-MASHI  ROAD") == "katsina daura mashi road"


def test_distinctive_tokens_drops_generic_words():
    tokens = distinctive_tokens("MAJOR MAINTENANCE OF OKWELLE-OJIAMA-IDEATO ROAD IN IMO STATE")
    assert tokens == ["okwelle", "ojiama", "ideato", "imo"]


def test_extract_phrases_handles_hyphenated_corridor():
    phrases = extract_phrases("SPECIAL REPAIRS OF KATSINA-DAURA-MASHI ROAD KATSINA STATE")
    joined = " ".join(phrases)
    assert "katsina daura mashi" in joined


def test_extract_phrases_handles_from_to_form():
    phrases = extract_phrases("REHABILITATION OF ROAD FROM KAURA NAMODA TO JIBIYA")
    assert any("kaura namoda" in phrase for phrase in phrases)


def test_exact_name_match_scores_one():
    scored = score_match(
        "MAINTENANCE OF KATSINA ALA-ZAKI BIAM-WUKARI ROAD IN BENUE STATE",
        "Katsina Ala - Zaki Biam - Wukari Road",
    )
    assert scored.confidence == "high"
    assert scored.shared >= 3


def test_spelling_drift_still_matches():
    scored = score_match("REHABILITATION OF KARLHI-JADA ROAD", "Karlahi - Jada Road")
    assert scored.shared >= 2
    assert scored.confidence in {"high", "medium"}


def test_unrelated_roads_do_not_match():
    scored = score_match("MAINTENANCE OF OKWELLE-OJIAMA-IDEATO ROAD", "Sokoto - Badagry Highway")
    assert scored.confidence == "none"


def test_single_common_token_is_not_high_confidence():
    scored = score_match("JADA ROAD", "Karlahi - Jada Road")
    assert scored.confidence != "high"
