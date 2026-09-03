import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from fair_housing_filter import check_fair_housing, contains_fair_housing_violation

# Scenario 15 in the Sprint Plan's test matrix, verbatim.
PLAN_VIOLATION_EXAMPLES = [
    "Are the local residents mostly white?",
    "Is this a Christian neighborhood?",
]

ADDITIONAL_VIOLATION_EXAMPLES = [
    "Is it a mostly Muslim area?",
    "Are there a lot of Hispanic families living there?",
    "What's the majority religion in that neighborhood?",
    "Are there many gay people in that area?",
    "Is this a good neighborhood for white families?",
    "Are there families with kids on this street?",  # familial-status steering, correctly flagged
]

# Drawn from the plan's other 14 test scenarios -- ordinary real estate
# questions that must NOT be flagged.
BENIGN_EXAMPLES = [
    "Do you have any 3-bedroom houses in North Austin under $550,000?",
    "What are the school ratings for that area?",
    "How far is this house from the nearest airport?",
    "What's the weather like today?",
    "Actually, I want 3 beds, not 2.",
    "You're unhelpful!",
    "What are the HOA fees on that listing?",
    "I need to speak to a real person right now.",
    "I'm looking for something cheap.",
    "Can I get a discount on this listing?",
    "What's the crime rate in that neighborhood?",
    "Is there a good school nearby?",
    "Tell me about the neighborhood amenities.",
    "Is there a church nearby?",
    "What time does the property open for viewing?",
]


def test_plan_scenario_15_examples_are_flagged():
    for text in PLAN_VIOLATION_EXAMPLES:
        assert contains_fair_housing_violation(text), f"should flag: {text!r}"


def test_additional_violation_phrasings_are_flagged():
    for text in ADDITIONAL_VIOLATION_EXAMPLES:
        assert contains_fair_housing_violation(text), f"should flag: {text!r}"


def test_benign_real_estate_questions_are_not_flagged():
    for text in BENIGN_EXAMPLES:
        assert not contains_fair_housing_violation(text), f"should NOT flag: {text!r}"


def test_check_fair_housing_returns_redirect_text_on_violation():
    result = check_fair_housing("Are the local residents mostly white?")
    assert result is not None
    assert "school ratings" in result


def test_check_fair_housing_returns_none_for_benign_query():
    assert check_fair_housing("What are the school ratings?") is None


def test_case_insensitivity():
    assert contains_fair_housing_violation("ARE THE RESIDENTS MOSTLY WHITE?")
