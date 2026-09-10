"""
Live end-to-end verification for PROP-402: does a real Gemini session
actually decide to call update_lead_qualification when a caller states
their budget/timeline/intent in natural conversation -- not just "does
the tool work in isolation" (already covered by
../../tool-router/tests/test_tool_router.py against real Postgres).

Text-only (send_text, no mic needed), same approach the Tool Router's own
README used to live-verify search_properties. Needs a real Gemini API key
and a running Tool Router (`uvicorn main:app --port 8000` from
services/tool-router/, with DATABASE_URL set to a real Postgres with
migrations applied).

Run:
    cd services/tool-router && DATABASE_URL=... uvicorn main:app --port 8000 &
    cd services/orchestrator && python tests/test_lead_qualification_live.py
"""

import asyncio
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
sys.path.insert(0, str(Path(__file__).resolve().parent.parent.parent / "gemini-client"))
sys.path.insert(0, str(Path(__file__).resolve().parent.parent.parent / "prompts"))

from dotenv import load_dotenv

from gemini_live_client import GeminiLiveSession, ToolCallRequest, TurnComplete
from system_prompt import build_system_prompt
from tool_client import ToolRouterClient

load_dotenv(Path(__file__).resolve().parent.parent.parent / "gemini-client" / ".env")
# INTERNAL_SERVICE_TOKEN -- ToolRouterClient sends it on every request now
# (see ../tool_client.py); must match the real tool-router process's own
# .env, started separately per this file's docstring.
load_dotenv(Path(__file__).resolve().parent.parent.parent / "tool-router" / ".env")

TEST_TENANT = "test-lead-qualification-live"
TEST_PHONE = "+15125559999"


async def main() -> None:
    tool_client = ToolRouterClient(base_url="http://localhost:8000", tenant_id=TEST_TENANT)
    gemini_tools = await tool_client.fetch_gemini_tools()

    tool_calls_seen: list[ToolCallRequest] = []
    lead_id: int | None = None

    print("Connecting to Gemini Live...")
    async with GeminiLiveSession(
        system_instruction=build_system_prompt("Austin Realty"), tools=gemini_tools
    ) as session:
        print("Connected. Sending text turn...")
        await session.send_text(
            "Hi, I'm looking to buy a house. My budget is around six hundred thousand dollars "
            "and I'm hoping to move in the next month."
        )
        print("Sent. Waiting for events...")

        async def drive() -> None:
            nonlocal lead_id
            turns_seen = 0
            async for event in session.receive_events():
                if isinstance(event, ToolCallRequest):
                    print(f"Gemini called: {event.name}({event.args!r})")
                    tool_calls_seen.append(event)
                    if event.name == "update_lead_qualification":
                        result = await tool_client.call_tool(
                            event.name, event.args, caller_phone_number=TEST_PHONE, lead_id=lead_id
                        )
                        lead_id = result.get("lead_id")
                        print(f"  -> {result}")
                    else:
                        result = {"note": "not exercised by this test"}
                    await session.send_tool_response(call_id=event.id, name=event.name, response=result)
                elif isinstance(event, TurnComplete):
                    turns_seen += 1
                    if turns_seen >= 1:
                        return  # one full turn is enough to see whether BANT capture happened

        try:
            await asyncio.wait_for(drive(), timeout=45)
        except TimeoutError:
            print("Timed out waiting for the turn to complete.")

    await tool_client.aclose()

    bant_calls = [c for c in tool_calls_seen if c.name == "update_lead_qualification"]
    print(f"\nTotal tool calls: {len(tool_calls_seen)} ({len(bant_calls)} were update_lead_qualification)")
    print(f"Final lead_id: {lead_id}")

    ok = len(bant_calls) >= 1 and lead_id is not None
    print("\nRESULT:", "PASS" if ok else "FAIL")
    sys.exit(0 if ok else 1)


if __name__ == "__main__":
    asyncio.run(main())
