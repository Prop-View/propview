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
sys.path.append(str(Path(__file__).resolve().parent.parent / "fallback-pipeline"))  # append -- see tool-router/tools/_calendar_context.py

from dotenv import load_dotenv
from livekit import api, rtc

from conversation_context import ConversationContextStore
from gemini_live_client import GeminiLiveSession
from health_monitor import HealthMonitor
from tenant_branding import get_agency_name
from metrics import start_metrics_server
from orchestrator import CallOrchestrator, build_gemini_tools
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
# PROP-603 -- set to 0 to disable the /metrics endpoint entirely (e.g. running
# many of these processes locally at once, where each would try to bind the same port).
METRICS_PORT = int(os.environ.get("METRICS_PORT", "9090"))
# PROP-503/504 -- unset skips transfer setup entirely (transfer_to_human_agent
# then replies with a "not available" error rather than failing the call).
BROKER_PHONE_NUMBER = os.environ.get("BROKER_PHONE_NUMBER")
# PROP-501/502 -- all three unset skips the cascaded fallback entirely (a
# session error/latency spike just ends the call, as it did before this existed).
DEEPGRAM_API_KEY = os.environ.get("DEEPGRAM_API_KEY")
OPENAI_API_KEY = os.environ.get("OPENAI_API_KEY")
CARTESIA_API_KEY = os.environ.get("CARTESIA_API_KEY")
CARTESIA_VOICE_ID = os.environ.get("CARTESIA_VOICE_ID")
FALLBACK_LATENCY_THRESHOLD_MS = float(os.environ.get("FALLBACK_LATENCY_THRESHOLD_MS", "1200"))


def _build_fallback_session_factory(agency_name: str):
    """None if the fallback isn't fully configured. Deliberately imports
    CascadedFallbackSession lazily, inside here -- so a deployment that
    never sets these env vars doesn't need deepgram-sdk/openai/cartesia
    installed at all.

    `agency_name` is passed in (the already-resolved, possibly
    per-tenant one from tenant_branding.py), not read from the AGENCY_NAME
    global directly -- the fallback session must speak under the same
    agency name as the primary Gemini session it's standing in for, or a
    caller mid-call would hear the wrong name after a fallback switch."""
    if not (DEEPGRAM_API_KEY and OPENAI_API_KEY and CARTESIA_API_KEY and CARTESIA_VOICE_ID):
        return None

    async def factory():
        from cascaded_session import CascadedFallbackSession

        session = CascadedFallbackSession(
            deepgram_api_key=DEEPGRAM_API_KEY,
            openai_api_key=OPENAI_API_KEY,
            cartesia_api_key=CARTESIA_API_KEY,
            cartesia_voice_id=CARTESIA_VOICE_ID,
            system_prompt=build_system_prompt(agency_name),
        )
        await session.__aenter__()
        return session

    return factory


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
    conversation_context = ConversationContextStore(redis_url=REDIS_URL)
    tool_client = ToolRouterClient(base_url=TOOL_ROUTER_URL, tenant_id=TENANT_ID)
    remote_tools = await tool_client.fetch_gemini_tools()
    gemini_tools = build_gemini_tools(remote_tools)

    # PROP-602/docs/AGENCY_ONBOARDING.md Stage 2b: per-tenant branding
    # (tenant_settings.agency_name) takes priority over the process-level
    # AGENCY_NAME env var when DATABASE_URL is configured -- a shared
    # orchestrator process pool serving multiple tenants needs this to
    # vary by tenant_id, not be fixed per deployment. Falls back to the
    # env var (default "our brokerage") if DATABASE_URL is unset, or the
    # tenant hasn't set branding via PUT /admin/tenants/{id}/branding yet.
    # Resolved before _build_fallback_session_factory() below, so the
    # fallback session (if it's ever switched to mid-call) speaks under
    # the same agency name as the primary one, not a stale env-var default.
    agency_name = AGENCY_NAME
    if DATABASE_URL is not None:
        agency_name = await get_agency_name(DATABASE_URL, TENANT_ID, default=AGENCY_NAME)

    lk_api = api.LiveKitAPI(LIVEKIT_URL, LIVEKIT_API_KEY, LIVEKIT_API_SECRET) if BROKER_PHONE_NUMBER else None
    fallback_session_factory = _build_fallback_session_factory(agency_name)
    health_monitor = HealthMonitor(latency_threshold_ms=FALLBACK_LATENCY_THRESHOLD_MS) if fallback_session_factory else None

    async with GeminiLiveSession(
        system_instruction=build_system_prompt(agency_name), tools=gemini_tools
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
            lk_api=lk_api,
            broker_phone_number=BROKER_PHONE_NUMBER,
            health_monitor=health_monitor,
            fallback_session_factory=fallback_session_factory,
            conversation_context=conversation_context,
        )
        await orchestrator.start()
        logger.info("Orchestrator running -- waiting for the call to end (Ctrl+C to stop)")

        try:
            await call_ended.wait()
        finally:
            await orchestrator.aclose()
            await session_store.aclose()
            await conversation_context.aclose()
            if lk_api is not None:
                await lk_api.aclose()
            if room.isconnected():
                await room.disconnect()
            logger.info("Call ended, cleaned up.")


def main() -> None:
    load_dotenv()
    if len(sys.argv) != 2:
        sys.exit("Usage: python main.py <room-name>")
    if METRICS_PORT:
        start_metrics_server(METRICS_PORT)
        logger.info("Prometheus metrics available at http://localhost:%d/metrics", METRICS_PORT)
    try:
        asyncio.run(run_call(sys.argv[1]))
    except KeyboardInterrupt:
        pass


if __name__ == "__main__":
    main()
