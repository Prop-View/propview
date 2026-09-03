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

# gemini_live_client lives in the sibling services/gemini-client/ directory,
# not installed as a package -- add it to sys.path so this script (and the
# orchestrator module it imports) can find it without manual PYTHONPATH setup.
sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "gemini-client"))

from dotenv import load_dotenv
from livekit import api, rtc

from gemini_live_client import GeminiLiveSession
from orchestrator import CallOrchestrator
from session_store import SessionStore

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("main")

LIVEKIT_URL = os.environ.get("LIVEKIT_URL", "ws://localhost:7880")
LIVEKIT_API_KEY = os.environ.get("LIVEKIT_API_KEY", "devkey")
LIVEKIT_API_SECRET = os.environ.get("LIVEKIT_API_SECRET", "secret")
REDIS_URL = os.environ.get("REDIS_URL", "redis://localhost:6379")
AGENT_IDENTITY = "ai-agent"
AGENT_PERSONA = "You are a friendly, concise real estate voice assistant. Keep replies short and natural."


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

    async with GeminiLiveSession(system_instruction=AGENT_PERSONA) as gemini_session:
        orchestrator = CallOrchestrator(room=room, gemini_session=gemini_session, session_store=session_store)
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
