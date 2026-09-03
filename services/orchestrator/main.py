"""
Sprint 1 entrypoint: runs one CallOrchestrator against a LiveKit room.

This is deliberately the "basic" process the plan's PROP-105 calls for --
it connects to one named room and bridges it to Gemini for the life of
that call. It does not yet auto-dispatch on every new inbound call; that
needs LiveKit's Agent Worker / job-dispatch system, a separate later
wiring step once PROP-102 is actually deployed and real calls exist to
dispatch against.

Usage:
    python main.py <room-name>
"""

from __future__ import annotations

import asyncio
import logging
import os
import sys
from pathlib import Path

# gemini_live_client and system_prompt live in sibling service directories,
# not installed as packages -- add them to sys.path so this script (and the
# orchestrator module it imports) can find them without manual PYTHONPATH setup.
sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "gemini-client"))
sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "prompts"))
sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "vap-sidecar"))

from dotenv import load_dotenv
from livekit import api, rtc

from gemini_live_client import GeminiLiveSession
from orchestrator import CallOrchestrator
from session_store import SessionStore
from system_prompt import build_system_prompt
from tool_client import ToolRouterClient
from vap_processor import SpeechActivityDetector

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("main")

LIVEKIT_URL = os.environ.get("LIVEKIT_URL", "ws://localhost:7880")
LIVEKIT_API_KEY = os.environ.get("LIVEKIT_API_KEY", "devkey")
LIVEKIT_API_SECRET = os.environ.get("LIVEKIT_API_SECRET", "secret")
REDIS_URL = os.environ.get("REDIS_URL", "redis://localhost:6379")
TOOL_ROUTER_URL = os.environ.get("TOOL_ROUTER_URL", "http://localhost:8000")
DATABASE_URL = os.environ.get("DATABASE_URL")  # optional -- transcript saving skipped if unset
AGENT_IDENTITY = "ai-agent"
AGENCY_NAME = os.environ.get("AGENCY_NAME", "our brokerage")
TENANT_ID = os.environ.get("TENANT_ID", "default")
ENABLE_PREDICTIVE_BARGE_IN = os.environ.get("ENABLE_PREDICTIVE_BARGE_IN", "true").lower() != "false"


def make_token(room_name: str) -> str:
    grants = api.VideoGrants(room_join=True, room=room_name, can_publish=True, can_subscribe=True)
    return (
        api.AccessToken(LIVEKIT_API_KEY, LIVEKIT_API_SECRET)
        .with_identity(AGENT_IDENTITY)
        .with_grants(grants)
        .to_jwt()
    )


async def run_call(room_name: str) -> None:
    room = rtc.Room()
    call_ended = asyncio.Event()
    # "disconnected" fires only if OUR OWN connection drops (server-forced,
    # or we call room.disconnect() ourselves) -- it does NOT fire just
    # because the caller leaves. So a call also ends when the caller (the
    # only other participant in a one-on-one SIP room) disconnects, even
    # if the room itself lingers past that (e.g. its empty_timeout hasn't
    # elapsed yet).
    room.on("disconnected", lambda reason: call_ended.set())
    room.on(
        "participant_disconnected",
        lambda participant: call_ended.set() if not room.remote_participants else None,
    )

    await room.connect(LIVEKIT_URL, make_token(room_name))
    logger.info("Agent joined room %r", room_name)

    session_store = SessionStore(redis_url=REDIS_URL)
    tool_client = ToolRouterClient(base_url=TOOL_ROUTER_URL, tenant_id=TENANT_ID)
    gemini_tools = await tool_client.fetch_gemini_tools()

    async with GeminiLiveSession(
        system_instruction=build_system_prompt(AGENCY_NAME), tools=gemini_tools
    ) as gemini_session:
        # One detector per call -- its VADIterator carries hysteresis state
        # across audio windows, so it must not be shared between calls.
        vad_detector = SpeechActivityDetector() if ENABLE_PREDICTIVE_BARGE_IN else None
        orchestrator = CallOrchestrator(
            room=room,
            gemini_session=gemini_session,
            session_store=session_store,
            tool_client=tool_client,
            database_url=DATABASE_URL,
            tenant_id=TENANT_ID,
            vad_detector=vad_detector,
        )
        await orchestrator.start()
        logger.info("Orchestrator running -- waiting for the call to end (Ctrl+C to stop)")

        try:
            await call_ended.wait()
        finally:
            await orchestrator.aclose()
            await session_store.aclose()
            if room.isconnected():
                await room.disconnect()
            logger.info("Call ended, cleaned up.")


def main() -> None:
    load_dotenv()
    if len(sys.argv) != 2:
        sys.exit("Usage: python main.py <room-name>")
    try:
        asyncio.run(run_call(sys.argv[1]))
    except KeyboardInterrupt:
        pass


if __name__ == "__main__":
    main()
