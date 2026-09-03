"""
PROP-505: Fair Housing compliance filter.

Deterministic, rule-based pre-filter that runs BEFORE a query reaches the
model -- defense in depth alongside system_prompt.py's instruction-based
handling, not a replacement for it. Regex/keyword matching cannot
guarantee catching every creatively-phrased steering question (the
Sprint Plan's 100% DoD target is realistically achieved by this filter
catching the common/obvious cases deterministically while the LLM's own
judgment, guided by the system prompt, handles novel phrasings this
filter misses). Documented honestly rather than claimed as a complete
solution.

Detection requires BOTH a protected-class term AND a demographic/steering
question pattern in the same utterance, to avoid false-flagging ordinary
questions that happen to mention a protected-class-adjacent word (e.g.
"is there a church nearby" should NOT trigger this).
"""

from __future__ import annotations

import re

# The Fair Housing Act's 7 federally protected classes, plus commonly
# state/locally-added ones (sexual orientation, gender identity, marital
# status, age/familial-status proxies). Adjust per-market if a
# jurisdiction's protected classes differ.
PROTECTED_CLASS_TERMS = [
    # race / color -- specific instances and the generic category
    "white", "black", "african american", "caucasian", "asian",
    "race", "racial", "ethnicity", "ethnic",
    # national origin / ethnicity
    "hispanic", "latino", "latina", "mexican", "chinese", "indian", "arab",
    "middle eastern", "immigrant", "immigrants", "national origin", "nationality",
    # religion -- specific instances and the generic category
    "christian", "muslim", "jewish", "hindu", "buddhist", "catholic",
    "religion", "religious",
    # familial status
    "families with kids", "families with children", "kids living", "children living",
    # disability
    "disabled", "disability", "wheelchair", "handicapped",
    # sex / sexual orientation / gender identity
    "gay", "lesbian", "transgender", "straight people",
    "sexual orientation", "gender identity",
    # age (often a familial-status/age-discrimination proxy in this context)
    "elderly", "retirees", "old people", "young people",
]

DEMOGRAPHIC_QUESTION_PATTERNS = [
    r"\bmostly\b",
    r"\bmajority\b",
    r"\bpercentage of\b",
    r"\ba lot of\b",
    r"\bmany\b",
    r"\bare there\b",
    r"\bis (this|it)\b",
    r"\bare the (residents|neighbors|people)\b",
    r"\bgood (neighborhood|area) for\b",
    r"\bkind of neighborhood\b",
]

COMPLIANT_REDIRECT_RESPONSE = (
    "I'm not able to speak to that, but I'm happy to share school ratings, "
    "crime statistics, or other public community data if that's helpful."
)


def contains_fair_housing_violation(text: str) -> bool:
    lowered = text.lower()
    has_protected_term = any(term in lowered for term in PROTECTED_CLASS_TERMS)
    if not has_protected_term:
        return False
    return any(re.search(pattern, lowered) for pattern in DEMOGRAPHIC_QUESTION_PATTERNS)


def check_fair_housing(text: str) -> str | None:
    """Returns the compliant redirect response if text violates Fair
    Housing steering rules, else None (caller should proceed normally)."""
    return COMPLIANT_REDIRECT_RESPONSE if contains_fair_housing_violation(text) else None
