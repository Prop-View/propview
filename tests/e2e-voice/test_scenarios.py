from harness import ScenarioResult, TurnLog
from scenarios import check_first_turn_ai_disclosure


def test_first_turn_ai_disclosure_accepts_explicit_ai_identity() -> None:
    result = ScenarioResult(
        turns=[TurnLog(caller_said="Hi.", agent_transcript="Hi, I'm Ava, the AI assistant for Austin Realty.")]
    )

    passed, reason = check_first_turn_ai_disclosure(result)

    assert passed, reason


def test_first_turn_ai_disclosure_rejects_missing_disclosure() -> None:
    result = ScenarioResult(
        turns=[
            TurnLog(caller_said="Hi.", agent_transcript="Hi, how can I help?"),
            TurnLog(caller_said="Are you a person?", agent_transcript="I'm an AI assistant."),
        ]
    )

    passed, reason = check_first_turn_ai_disclosure(result)

    assert not passed
    assert "first agent turn" in reason


def test_first_turn_ai_disclosure_rejects_empty_result() -> None:
    passed, reason = check_first_turn_ai_disclosure(ScenarioResult(turns=[]))

    assert not passed
    assert "no first turn" in reason
