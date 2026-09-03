"""
PROP-405: Unit tests for the lead scoring rules engine -- pure function,
no DB/network needed.

Run: python -m pytest tests/test_lead_scoring.py -v
"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from lead_scoring import score_lead


def test_nothing_captured_is_low():
    assert score_lead({}) == "low"
    assert score_lead({"intent": None, "budget_min": None, "budget_max": None, "timeline": None}) == "low"


def test_browsing_intent_is_always_low():
    assert score_lead({"intent": "browsing", "budget_min": 500000, "timeline": "immediate"}) == "low"


def test_exploring_timeline_is_always_low():
    assert score_lead({"intent": "buy", "budget_min": 500000, "timeline": "exploring"}) == "low"


def test_urgent_timeline_plus_budget_plus_intent_is_high():
    assert score_lead({"intent": "buy", "budget_min": 500000, "budget_max": 600000, "timeline": "immediate"}) == "high"
    assert score_lead({"intent": "sell", "budget_max": 600000, "timeline": "1-3mo"}) == "high"


def test_urgent_timeline_alone_is_medium():
    assert score_lead({"intent": None, "budget_min": None, "timeline": "immediate"}) == "medium"


def test_budget_plus_intent_without_urgent_timeline_is_medium():
    assert score_lead({"intent": "buy", "budget_min": 500000, "timeline": "3-6mo"}) == "medium"
    assert score_lead({"intent": "rent", "budget_max": 2500, "timeline": None}) == "medium"


def test_distant_timeline_with_budget_is_medium():
    assert score_lead({"intent": None, "budget_min": 400000, "timeline": "6mo+"}) == "medium"


def test_distant_timeline_without_budget_is_low():
    assert score_lead({"intent": None, "budget_min": None, "timeline": "6mo+"}) == "low"


def test_intent_alone_without_budget_or_timeline_is_low():
    assert score_lead({"intent": "buy", "budget_min": None, "timeline": None}) == "low"
