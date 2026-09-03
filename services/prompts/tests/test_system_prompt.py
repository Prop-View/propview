import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from system_prompt import build_system_prompt


def test_default_prompt_has_placeholder_agency():
    prompt = build_system_prompt()
    assert "our brokerage" in prompt


def test_agency_name_is_substituted():
    prompt = build_system_prompt(agency_name="Austin Realty Group")
    assert "Austin Realty Group" in prompt
    assert "{agency_name}" not in prompt


def test_fair_housing_rule_present():
    prompt = build_system_prompt()
    assert "Fair Housing" in prompt
    assert "racial" in prompt.lower()


def test_prompt_instructs_brevity_for_voice():
    prompt = build_system_prompt()
    assert "one or two sentences" in prompt
