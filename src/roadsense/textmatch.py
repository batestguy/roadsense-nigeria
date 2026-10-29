"""Extract road phrases from procurement text and score them against GRID3 segment names.

The matching problem in one sentence: procurement records name roads the way ministries talk
("SPECIAL REPAIRS OF KATSINA-DAURA-MASHI ROAD KATSINA STATE"), while GRID3 names them the way
OpenStreetMap does ("Katsina - Daura - Mashi Road"). Both describe the same corridor, so the job
is to compare *distinctive place tokens* and ignore everything else.

Two deliberate compromises:

1. Generic words (road, maintenance, rehabilitation, state, ...) carry no identity and are dropped
   from both sides before comparison.
2. Spelling varies ("Karlahi" vs "Karlhi"), so tokens are compared with a fuzzy ratio rather than
   requiring exact equality. The threshold is high enough that different roads rarely collide.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from difflib import SequenceMatcher

#: Words that appear in nearly every procurement description and identify nothing.
GENERIC_TOKENS: frozenset[str] = frozenset(
    """
    road roads rd highway highways expressway expressways byepass bypass carriageway way
    street route the of in at on to from for and with by a an
    general major minor special routine planned preventive periodic emergency urgent
    comprehensive total partial
    maintenance repair repairs rehabilitation rehabilitate reconstruct reconstructed
    reconstruction construction construct dualisation dualization dualling widening
    overlay resurfacing resurface patching patch reinstatement reinstatements
    improvement improvements upgrading upgrade
    section sections segment portion part lot phase project projects job contract works work
    supply supplies procurement
    state states lga local government area areas
    access link spur township internal township
    drainage culvert culverts erosion flood floods flooding
    asphalt laterite bitumen concrete surface
    north south east west central northern southern eastern western
    federal fgn government ministry agency
    republic border borders boundary international frontier customs post
    township interchange junction roundabout flyover
    works contract contractor bidding tender
    """.split()
)

#: Tokens that mark where a road name ends.
ROAD_WORDS: frozenset[str] = frozenset(
    {"road", "roads", "rd", "highway", "expressway", "bypass", "byepass", "carriageway"}
)

#: How many tokens before a road keyword to consider.
_PRECEDING_WINDOW = 6

#: Similarity above which two tokens are treated as the same place name.
FUZZY_TOKEN_THRESHOLD = 0.85

_SPLIT = re.compile(r"[^a-z0-9]+")
_FROM_TO = re.compile(r"\bfrom\s+(.{3,40}?)\s+to\s+(.{3,40})", re.IGNORECASE)
_DASH_PAIR = re.compile(r"([a-z]{3,}(?:[\s\-]+[a-z]{3,}){0,3})\s*[-–—/]\s*([a-z]{3,}(?:[\s\-]+[a-z]{3,}){0,3})")


def normalise(text: str) -> str:
    """Lowercase, strip punctuation, collapse whitespace."""
    lowered = text.lower().replace("&", " and ")
    return " ".join(_SPLIT.sub(" ", lowered).split())


def tokenise(text: str) -> list[str]:
    """Split normalised text into raw tokens (generic words retained)."""
    return normalise(text).split()


def distinctive_tokens(text: str) -> list[str]:
    """Tokens that can identify a place, in original order, duplicates removed."""
    seen: set[str] = set()
    out: list[str] = []
    for token in tokenise(text):
        if token in GENERIC_TOKENS or len(token) < 3:
            continue
        if token not in seen:
            seen.add(token)
            out.append(token)
    return out


def extract_phrases(text: str) -> list[str]:
    """Return candidate road phrases from a procurement description.

    Multiple candidates are returned because a title can mention more than one road;
    the caller scores each and keeps the best.
    """
    if not text:
        return []

    phrases: list[str] = []
    lowered = text.lower()

    # "REHABILITATION OF ROAD FROM A TO B" -> "A B"
    for match in _FROM_TO.finditer(lowered):
        phrases.append(f"{match.group(1)} {match.group(2)}")

    # "KATSINA-DAURA-MASHI ROAD" -> token window around the road word
    tokens = tokenise(lowered)
    for index, token in enumerate(tokens):
        if token not in ROAD_WORDS:
            continue
        start = max(0, index - _PRECEDING_WINDOW)
        window = tokens[start:index]
        if window:
            phrases.append(" ".join(window))
        # Trailing names: "ROAD A - B"
        trailing = tokens[index + 1 : index + 4]
        if len(trailing) >= 2 and all(t not in GENERIC_TOKENS for t in trailing):
            phrases.append(" ".join(trailing))

    # Deduplicate, keep phrases that survive the generic filter with at least one token.
    unique: list[str] = []
    seen: set[str] = set()
    for phrase in phrases:
        key = " ".join(distinctive_tokens(phrase))
        if key and key not in seen:
            seen.add(key)
            unique.append(phrase)
    return unique


@dataclass(frozen=True)
class MatchScore:
    """How well a procurement phrase matches a segment name."""

    score: float          # 0..1, blended precision/recall
    shared: int           # number of place tokens in common (exact + fuzzy)
    exact_anchor: bool    # the normalised strings are identical
    confidence: str       # high | medium | low | none

    @property
    def is_usable(self) -> bool:
        return self.confidence == "high"


def _fuzzy_shared(left: list[str], right: list[str]) -> tuple[int, list[tuple[str, str]]]:
    """Count shared tokens, allowing near-miss spellings, and record the pairs."""
    right_pool = set(right)
    shared = 0
    pairs: list[tuple[str, str]] = []
    for token in left:
        if token in right_pool:
            shared += 1
            pairs.append((token, token))
            right_pool.discard(token)
            continue
        best_ratio, best = 0.0, None
        for candidate in right_pool:
            ratio = SequenceMatcher(None, token, candidate).ratio()
            if ratio > best_ratio:
                best_ratio, best = ratio, candidate
        if best is not None and best_ratio >= FUZZY_TOKEN_THRESHOLD:
            shared += 1
            pairs.append((token, best))
            right_pool.discard(best)
    return shared, pairs


def score_match(phrase: str, candidate_name: str) -> MatchScore:
    """Score a procurement road phrase against a GRID3 segment name."""
    left = distinctive_tokens(phrase)
    right = distinctive_tokens(candidate_name)

    if not left or not right:
        return MatchScore(0.0, 0, False, "none")

    exact_anchor = " ".join(left) == " ".join(right)
    shared, _pairs = _fuzzy_shared(left, right)

    if shared == 0:
        return MatchScore(0.0, 0, exact_anchor, "none")

    union = len(left) + len(right) - shared
    jaccard = shared / union if union else 0.0
    containment = shared / min(len(left), len(right))
    score = 0.5 * jaccard + 0.5 * containment
    if exact_anchor:
        score = 1.0

    # Confidence bands. `min_shared` exists because a single common token is usually a
    # coincidence ("jada" appears in many road names across a state).
    if exact_anchor or (shared >= 2 and score >= 0.60):
        confidence = "high"
    elif containment == 1.0 and len(left) >= 2 and shared >= 2:
        confidence = "high"
    elif (shared >= 2 and score >= 0.35) or (shared == 1 and len(left[0]) >= 6 and containment == 1.0):
        confidence = "medium"
    else:
        confidence = "low"

    return MatchScore(round(score, 4), shared, exact_anchor, confidence)
