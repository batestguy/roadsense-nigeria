"""Gate G0 — match procurement interventions to GRID3 road segments.

This is the project's go/no-go test. If the open procurement record cannot be joined to the
road network at usable precision, no amount of satellite engineering saves the project, and
it is far cheaper to discover that now than after the imagery backfill.

Search strategy, cheapest first:

1. Exact token lookup through an inverted index (token -> segments).
2. Fuzzy token expansion, blocked on the first two characters, to absorb spelling drift
   ("Karlahi" / "Karlhi").
3. Every candidate is restricted to segments inside the event's state, which removes the
   large majority of false positives before scoring.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from difflib import SequenceMatcher

import pandas as pd

from roadsense import config
from roadsense.textmatch import (
    FUZZY_TOKEN_THRESHOLD,
    MatchScore,
    distinctive_tokens,
    score_match,
)

#: Never score more than this many candidates per event; keeps runtime bounded.
MAX_CANDIDATES = 400


@dataclass
class SegmentIndex:
    """In-memory index over named segments, keyed for fast phrase lookup."""

    names: list[str]
    tokens: list[list[str]]
    states: list[str | None]
    classes: list[str]
    ids: list[str]
    by_token: dict[str, list[int]] = field(default_factory=dict)
    by_prefix: dict[str, list[str]] = field(default_factory=dict)

    @classmethod
    def build(cls, segments: pd.DataFrame) -> SegmentIndex:
        names = segments["names"].fillna("").astype(str).tolist()
        states = segments["state"].tolist()
        classes = segments["road_class"].fillna("").astype(str).tolist()
        ids = segments["segment_id"].astype(str).tolist()
        tokens = [distinctive_tokens(name) for name in names]

        index = cls(names=names, tokens=tokens, states=states, classes=classes, ids=ids)
        for position, segment_tokens in enumerate(tokens):
            for token in segment_tokens:
                index.by_token.setdefault(token, []).append(position)
        for token in index.by_token:
            index.by_prefix.setdefault(token[:2], []).append(token)
        index.by_prefix = {key: sorted(values) for key, values in index.by_prefix.items()}
        return index

    def expand_token(self, token: str) -> list[str]:
        """Return the token itself plus any near-spellings that exist in the network."""
        if token in self.by_token:
            return [token]
        matches: list[str] = []
        for candidate in self.by_prefix.get(token[:2], []):
            if abs(len(candidate) - len(token)) > 3:
                continue
            if SequenceMatcher(None, token, candidate).ratio() >= FUZZY_TOKEN_THRESHOLD:
                matches.append(candidate)
        return matches


def match_events(events: pd.DataFrame, segments: pd.DataFrame) -> pd.DataFrame:
    """Attach the best-matching segment (and its score) to each procurement event."""
    index = SegmentIndex.build(segments)

    records: list[dict] = []
    for row in events.itertuples(index=False):
        phrase = getattr(row, "road_phrase", None)
        state = getattr(row, "state", None)

        best = _best_candidate(index, phrase, state)
        records.append(
            {
                "ocid": row.ocid,
                "year": getattr(row, "year", None),
                "state": state,
                "road_phrase": phrase,
                "amount": getattr(row, "amount", None),
                "segment_id": best["segment_id"],
                "matched_name": best["name"],
                "matched_class": best["road_class"],
                "score": best["score"],
                "shared_tokens": best["shared"],
                "exact_anchor": best["exact"],
                "confidence": best["confidence"],
                "candidates": best["candidates"],
                "rule": best["rule"],
            }
        )

    return pd.DataFrame.from_records(records)


#: A cross-state match must clear this bar. Many Nigerian highways run through two or three
#: states, so requiring the segment's state to equal the state named in the contract loses
#: genuine matches ("Abuja-Keffi Expressway" is labelled FCT but its segments fall in Nasarawa).
#: The token evidence has to be strong enough to stand on its own before we allow it.
CROSS_STATE_MIN_SHARED = 3


def _candidate_positions(index: SegmentIndex, phrase_tokens: list[str]) -> set[int]:
    """Segment positions sharing at least one (exactly or fuzzily) matched token."""
    positions: set[int] = set()
    for token in phrase_tokens:
        for expanded in index.expand_token(token):
            positions.update(index.by_token.get(expanded, ()))
    return positions


def _best_in(index: SegmentIndex, phrase: str, phrase_tokens: list[str], positions: set[int]):
    """Best-scoring candidate among ``positions``, or (None, None)."""
    if not positions:
        return None, None
    if len(positions) > MAX_CANDIDATES:
        # Too many to score individually; keep the ones sharing the most tokens.
        overlap = [
            (position, len(set(phrase_tokens) & set(index.tokens[position])))
            for position in positions
        ]
        overlap.sort(key=lambda pair: pair[1], reverse=True)
        positions = {position for position, _ in overlap[:MAX_CANDIDATES]}

    best: MatchScore | None = None
    best_position: int | None = None
    for position in positions:
        scored = score_match(phrase, index.names[position])
        if best is None or _rank(scored) > _rank(best):
            best, best_position = scored, position
    return best, best_position


def _best_candidate(index: SegmentIndex, phrase: str | None, state: str | None) -> dict:
    """Find the best-matching segment for ``phrase``, preferring the event's own state."""
    empty = {
        "segment_id": None,
        "name": None,
        "road_class": None,
        "score": 0.0,
        "shared": 0,
        "exact": False,
        "confidence": "none",
        "candidates": 0,
        "rule": "none",
    }
    if not phrase:
        return empty

    phrase_tokens = distinctive_tokens(phrase)
    if not phrase_tokens:
        return empty

    all_positions = _candidate_positions(index, phrase_tokens)
    in_state = {p for p in all_positions if index.states[p] == state} if state else set()

    best, best_position = _best_in(index, phrase, phrase_tokens, in_state)
    rule = "in_state"

    if best is None or best.confidence != "high":
        # Fall back to a national search, but only accept it on strong token evidence.
        elsewhere = all_positions - in_state
        other, other_position = _best_in(index, phrase, phrase_tokens, elsewhere)
        if other is not None and other_position is not None:
            strong_enough = other.exact_anchor or other.shared >= CROSS_STATE_MIN_SHARED
            if strong_enough and (best is None or _rank(other) > _rank(best)):
                best, best_position, rule = other, other_position, "cross_state"

    if best_position is None or best is None:
        return empty

    return {
        "segment_id": index.ids[best_position],
        "name": index.names[best_position],
        "road_class": index.classes[best_position],
        "score": best.score,
        "shared": best.shared,
        "exact": best.exact_anchor,
        "confidence": best.confidence,
        "candidates": len(all_positions),
        "rule": rule,
    }


_CONFIDENCE_RANK = {"high": 3, "medium": 2, "low": 1, "none": 0}


def _rank(score: MatchScore) -> tuple[int, float, int]:
    return (_CONFIDENCE_RANK[score.confidence], score.score, score.shared)


def diagnose_unmatched(matches: pd.DataFrame, segments: pd.DataFrame) -> dict[str, int]:
    """Explain *why* each unmatched event failed, rather than only counting failures.

    Three distinct causes, and they mean different things for the project:

    ``road_absent_from_grid3`` — the phrase contains no token that appears in any named road
        in the country. The road is simply not named in the network; no matcher can fix this.
    ``single_token_only`` — only one token is shared with the whole national vocabulary. One
        shared token cannot establish identity without guessing.
    ``below_confidence`` — two or more tokens line up but not well enough to accept.
    """
    index = SegmentIndex.build(segments)
    reasons: dict[str, int] = {
        "road_absent_from_grid3": 0,
        "single_token_only": 0,
        "below_confidence": 0,
    }
    for row in matches[matches["confidence"] == "none"].itertuples(index=False):
        tokens = distinctive_tokens(str(row.road_phrase))
        tokens_with_hits = [token for token in tokens if index.expand_token(token)]
        if not tokens_with_hits:
            reasons["road_absent_from_grid3"] += 1
        elif len(tokens_with_hits) < 2:
            reasons["single_token_only"] += 1
        else:
            reasons["below_confidence"] += 1
    return reasons


def summarise(matches: pd.DataFrame) -> dict:
    """Aggregate the match results into the numbers the gate is judged on."""
    with_phrase = matches[matches["road_phrase"].notna()]
    high = with_phrase[with_phrase["confidence"] == "high"]

    return {
        "events": int(len(matches)),
        "events_with_state_and_phrase": int(len(with_phrase)),
        "high": int((matches["confidence"] == "high").sum()),
        "medium": int((matches["confidence"] == "medium").sum()),
        "low": int((matches["confidence"] == "low").sum()),
        "none": int((matches["confidence"] == "none").sum()),
        "unique_segments_high": int(high["segment_id"].nunique()),
        "unique_road_names_high": int(high["matched_name"].nunique()),
        "median_score_high": float(high["score"].median()) if len(high) else 0.0,
    }


def verdict(summary: dict) -> str:
    """Apply the thresholds committed to in preflight-spec.md §5."""
    high = summary["high"]
    if high >= config.GATE_PROCEED:
        return "PROCEED — national scope is defensible"
    if high >= config.GATE_CONDITIONAL:
        return "PROCEED CONDITIONALLY — scope to states with adequate label coverage"
    return "STOP — re-scope before building further"
