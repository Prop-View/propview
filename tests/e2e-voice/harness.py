"""
PROP-604/207: E2E voice scenario test harness.

**Text-driven** (via `GeminiLiveSession.send_text`), not literal
audio-injection -- an honest scope decision, not an oversight. The
plan's 15 scenarios (Sprint Plan.md section 3) are fundamentally about
*conversational behavior* (does the AI pivot back to real estate after
an unrelated question, does it correctly redirect a steering question,
does it call transfer_to_human_agent when asked for a manager) --
exercising that behavior needs real Gemini reasoning either way, and
text-in reaches the exact same downstream logic (tool calling, transcript
capture, turn-taking) that matters for regression testing, without the
extra complexity/flakiness of synthesizing and injecting WAV audio into
a LiveKit room for each of 15+ scenarios. `../../services/gemini-client/`'s
own tests made the same call for the same reason. Real audio-path
behavior (barge-in timing, VAD accuracy) is already covered separately
by `../../services/orchestrator/tests/test_predictive_barge_in_live.py`.

Drives one real Gemini session + real Tool Router through a scripted
multi-turn conversation, capturing the full event stream for a
scenario's `check` function to assert against.
"""

from __future__ import annotations

import asyncio
import sys
from dataclasses import dataclass, field
from pathlib import Path
from typing import Callable

_SERVICES = Path(__file__).resolve().parent.parent.parent / "services"
sys.path.insert(0, str(_SERVICES / "gemini-client"))
sys.path.insert(0, str(_SERVICES / "prompts"))
sys.path.insert(0, str(_SERVICES / "orchestrator"))

from gemini_live_client import GeminiLiveSession, ToolCallRequest, TranscriptChunk, TurnComplete  # noqa: E402
from orchestrator import build_gemini_tools  # noqa: E402
from system_prompt import build_system_prompt  # noqa: E402
from tool_client import ToolRouterClient  # noqa: E402

TURN_TIMEOUT_SECONDS = 30


@dataclass
class TurnLog:
    caller_said: str
    tool_calls: list[ToolCallRequest] = field(default_factory=list)
    agent_transcript: str = ""


@dataclass
class ScenarioResult:
    turns: list[TurnLog]

    @property
    def all_tool_calls(self) -> list[ToolCallRequest]:
        return [c for turn in self.turns for c in turn.tool_calls]

    @property
    def tool_call_names(self) -> list[str]:
        return [c.name for c in self.all_tool_calls]

    @property
    def full_agent_transcript(self) -> str:
        return " ".join(turn.agent_transcript for turn in self.turns)


@dataclass
class Scenario:
    name: str
    caller_turns: list[str]  # what the caller says, one string per turn
    check: Callable[[ScenarioResult], tuple[bool, str]]  # (passed, reason)
    tenant_id: str = "test-e2e-voice"
    caller_phone_number: str = "+15125559876"
    agency_name: str = "Austin Realty"


async def run_scenario(scenario: Scenario, tool_router_url: str = "http://localhost:8000") -> tuple[bool, str, ScenarioResult]:
    tool_client = ToolRouterClient(base_url=tool_router_url, tenant_id=scenario.tenant_id)
    remote_tools = await tool_client.fetch_gemini_tools()
    # Must merge in the local-only transfer_to_human_agent declaration the
    # same way main.py does -- omitting this was a real bug caught while
    # building this harness: without it, Gemini has no way to know the
    # tool exists at all, and (correctly, given its instructions for a
    # tool that truly isn't available) apologizes and says it can't
    # transfer instead of ever attempting to call it.
    gemini_tools = build_gemini_tools(remote_tools)

    turns: list[TurnLog] = []
    lead_id: int | None = None

    async with GeminiLiveSession(
        system_instruction=build_system_prompt(scenario.agency_name), tools=gemini_tools
    ) as session:
        for caller_text in scenario.caller_turns:
            await session.send_text(caller_text)
            turn_log = TurnLog(caller_said=caller_text)

            async def drive_one_turn() -> None:
                nonlocal lead_id
                async for event in session.receive_events():
                    if isinstance(event, ToolCallRequest):
                        turn_log.tool_calls.append(event)
                        if event.name == "transfer_to_human_agent":
                            # Local-only tool (see orchestrator.py's
                            # _handle_tool_call) -- never forwarded to the
                            # Tool Router, which 404s on it (a real bug
                            # this harness hit before this branch existed).
                            # This harness only cares whether Gemini
                            # *decided* to call it, not exercising the
                            # real SIP transfer -- that's covered by
                            # ../../services/orchestrator/tests/test_human_transfer.py.
                            response = {"status": "transferred"}
                        else:
                            # Mirrors orchestrator.py's _handle_tool_call:
                            # a tool error (e.g. check_calendar_slots on a
                            # tenant with no calendar configured -- a real,
                            # expected 422) gets reported back to Gemini as
                            # an error response, not left to crash the
                            # whole scenario run. Letting it propagate was
                            # a real bug this harness hit before this
                            # try/except existed.
                            try:
                                result = await tool_client.call_tool(
                                    event.name, event.args, caller_phone_number=scenario.caller_phone_number, lead_id=lead_id
                                )
                                if event.name in ("update_lead_qualification", "book_site_visit") and isinstance(result, dict):
                                    lead_id = result.get("lead_id", lead_id)
                                response = {"result": result}
                            except Exception as exc:  # noqa: BLE001 -- always report back to Gemini, even on failure
                                response = {"error": str(exc)}
                        await session.send_tool_response(call_id=event.id, name=event.name, response=response)
                    elif isinstance(event, TranscriptChunk) and event.speaker == "agent":
                        # NOT gated on event.finished -- a real, surprising
                        # finding while building this harness: for
                        # multi-sentence agent replies, `finished` never
                        # actually arrived True before TurnComplete fired
                        # (every chunk stayed finished=False). Only
                        # confirmed for text-driven turns so far; worth
                        # checking whether real audio-driven turns behave
                        # the same way, since orchestrator.py's own
                        # transcript capture (_record_transcript_chunk)
                        # has this exact same dependency on `finished` and
                        # would silently lose the same text if so -- see
                        # ../../services/gemini-client/README.md.
                        turn_log.agent_transcript += event.text
                    elif isinstance(event, TurnComplete):
                        return

            try:
                await asyncio.wait_for(drive_one_turn(), timeout=TURN_TIMEOUT_SECONDS)
            except TimeoutError:
                pass  # scored as-is -- a scenario whose check needed more won't pass, which is itself a finding
            turns.append(turn_log)

    await tool_client.aclose()
    result = ScenarioResult(turns=turns)
    passed, reason = scenario.check(result)
    return passed, reason, result
