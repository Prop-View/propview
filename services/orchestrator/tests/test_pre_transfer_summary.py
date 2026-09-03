"""
PROP-504: Unit tests for the pre-transfer SMS summary builder -- pure
function, no DB/network needed.

Run: python -m pytest tests/test_pre_transfer_summary.py -v
"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from pre_transfer_summary import MAX_SMS_BODY_CHARS, build_pre_transfer_summary


def test_includes_caller_phone_and_reason():
    body = build_pre_transfer_summary("+15125551234", "asked for a human", None, [])
    assert "+15125551234" in body
    assert "asked for a human" in body


def test_missing_phone_number_shows_unknown():
    body = build_pre_transfer_summary(None, None, None, [])
    assert "unknown" in body


def test_includes_lead_snapshot_fields():
    lead = {"intent": "buy", "budget_min": 500000, "budget_max": 600000, "timeline": "immediate", "priority": "high"}
    body = build_pre_transfer_summary("+15125551234", None, lead, [])
    assert "intent=buy" in body
    assert "budget=500000-600000" in body
    assert "timeline=immediate" in body
    assert "priority=high" in body


def test_omits_lead_line_when_snapshot_has_no_useful_fields():
    body = build_pre_transfer_summary("+15125551234", None, {"intent": None, "priority": None}, [])
    assert "Lead:" not in body


def test_includes_only_recent_caller_transcript_lines():
    transcript = [
        "Agent: Hello, how can I help?",
        "Caller: I want a 3 bedroom house",
        "Agent: Sure, let me look",
        "Caller: Budget is 500k",
        "Caller: Actually make that 600k",
        "Caller: And I need it by next month",
    ]
    body = build_pre_transfer_summary("+15125551234", None, None, transcript)
    assert "I want a 3 bedroom house" not in body  # older than the last 3 caller lines
    assert "Budget is 500k" in body
    assert "Actually make that 600k" in body
    assert "And I need it by next month" in body
    assert "how can I help" not in body  # agent lines excluded


def test_truncates_to_max_length():
    huge_transcript = [f"Caller: {'x' * 200}" for _ in range(10)]
    body = build_pre_transfer_summary("+15125551234", "reason", {"intent": "buy"}, huge_transcript)
    assert len(body) <= MAX_SMS_BODY_CHARS
