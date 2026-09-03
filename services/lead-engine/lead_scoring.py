"""
PROP-405: Lead scoring rules engine -- High/Medium/Low priority tagger.

A deterministic rules table over the BANT fields captured by
update_lead_qualification (../tool-router/tools/update_lead_qualification.py,
PROP-402), not a model -- the plan calls this a "rules engine," and BANT
fields are already structured/categorical (not free text needing NLP), so
a small ordered set of rules is both simpler and more auditable than
training or prompting anything for this.

Deliberately conservative: qualification is expected to be partial (the
plan's Qualification Capture Rate target is >80% of *fields*, not 100% of
calls) -- a lead with nothing captured yet scores "low," not "unknown."
Re-run every time update_lead_qualification is called, so priority
tracks the lead's *current* known state as more fields get captured
through the call, not a one-time snapshot.
"""

from __future__ import annotations

from typing import Literal

Priority = Literal["high", "medium", "low"]

URGENT_TIMELINES = {"immediate", "1-3mo"}


def score_lead(fields: dict) -> Priority:
    """`fields` -- a dict with (at least) `intent`, `budget_min`,
    `budget_max`, `timeline` keys, any of which may be None/absent. Shape
    matches a `leads` row (db/migrations/003_crm_schema.sql), so a raw
    asyncpg Record can be passed in directly via dict(row)."""
    intent = fields.get("intent")
    timeline = fields.get("timeline")
    has_budget = fields.get("budget_min") is not None or fields.get("budget_max") is not None
    has_intent_to_transact = intent in ("buy", "sell", "rent")

    # Explicit low-intent signals override everything else -- a browser
    # with a budget number isn't suddenly a hot lead.
    if intent == "browsing" or timeline == "exploring":
        return "low"

    # Nothing meaningfully captured yet.
    if intent is None and timeline is None and not has_budget:
        return "low"

    # The strongest signal: ready to transact soon AND knows their budget.
    if timeline in URGENT_TIMELINES and has_budget and has_intent_to_transact:
        return "high"

    # One strong signal (urgent timeline, or budget + real intent) but not both.
    if timeline in URGENT_TIMELINES or (has_budget and has_intent_to_transact):
        return "medium"

    # Some signal, but distant timeline (6mo+) or an incomplete picture.
    if timeline == "6mo+" and has_budget:
        return "medium"

    return "low"
