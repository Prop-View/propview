"""
PROP-105 follow-up (auto-dispatch): everything needed to run one call's
worth of CallOrchestrator against an already-connected LiveKit room --
extracted out of main.py so main.py (manual, one room, started by hand)
and worker.py (auto-dispatched, triggered by LiveKit's Agent framework on
every new inbound call) share one implementation instead of two copies
that would quietly drift apart.

The one thing this module deliberately does NOT do is connect the room --
callers differ in how they get there (main.py: `room.connect(url, token)`
with an explicit room name; worker.py: the dispatched job's
`ctx.connect()`) -- and get a `tenant_id` resolved their own way (main.py:
a single process-wide env var; worker.py: per-call, from the dispatched
job's metadata -- see worker.py's own docstring for why). Everything from
"the room is connected and we know which tenant this is" onward is
identical regardless of how either of those happened, which is exactly
what's shared here.
"""

from __future__ import annotations

import asyncio
import logging
import os
import sys
from pathlib import Path

# Same sys.path setup main.py has always needed -- gemini_live_client,
# system_prompt, vap_processor, and the fallback pipeline all live in
# sibling service directories, not installed as packages. Done here
# (not in main.py/worker.py individually) so importing this module is
# sufficient on its own; see tool-router/tools/_calendar_context.py for
# why fallback-pipeline is appended, not inserted first (keeps gemini-client's
# google-genai takng precedence over anything fallback-pipeline's deps
# might shadow).
sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "gemini-client"))
sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "prompts"))
sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "vap-sidecar"))
sys.path.append(str(Path(__file__).resolve().parent.parent / "fallback-pipeline"))

from livekit import api, rtc  # noqa: E402

from conversation_context import ConversationContextStore  # noqa: E402
from gemini_live_client import GeminiLiveSession  # noqa: E402
from health_monitor import HealthMonitor  # noqa: E402
from tenant_branding import get_agency_name  # noqa: E402
from orchestrator import CallOrchestrator, build_gemini_tools  # noqa: E402
from session_store import SessionStore  # noqa: E402
from system_prompt import build_system_prompt  # noqa: E402
from tool_client import ToolRouterClient  # noqa: E402
from vap_processor import SpeechActivityDetector  # noqa: E402

logger = logging.getLogger("call_session")

LIVEKIT_URL = os.environ.get("LIVEKIT_URL", "ws://localhost:7880")
LIVEKIT_API_KEY = os.environ.get("LIVEKIT_API_KEY", "devkey")
LIVEKIT_API_SECRET = os.environ.get("LIVEKIT_API_SECRET", "secret")
REDIS_URL = os.environ.get("REDIS_URL", "redis://localhost:6379")
TOOL_ROUTER_URL = os.environ.get("TOOL_ROUTER_URL", "http://localhost:8000")
DATABASE_URL = os.environ.get("DATABASE_URL")  # optional -- transcript saving skipped if unset
AGENCY_NAME = os.environ.get("AGENCY_NAME", "our brokerage")
ENABLE_PREDICTIVE_BARGE_IN = os.environ.get("ENABLE_PREDICTIVE_BARGE_IN", "true").lower() != "false"
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
    per-tenant one), not read from the AGENCY_NAME global directly --
    the fallback session must speak under the same agency name as the
    primary Gemini session it's standing in for, or a caller mid-call
    would hear the wrong name after a fallback switch."""
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


async def run_orchestrator_on_room(room: rtc.Room, tenant_id: str) -> None:
    """Builds every per-call dependency, runs a CallOrchestrator against
    `room` until the call ends, then tears everything down.

    Preconditions the caller is responsible for: `room` is already
    connected to LiveKit, and `tenant_id` has already been resolved
    (main.py: a fixed env var; worker.py: per-call from job metadata).
    Everything else -- session store, Tool Router client, per-tenant
    branding, the Gemini session, VAD, the fallback factory, the
    CallOrchestrator itself, and waiting for the call to actually end --
    is identical regardless of which entrypoint got us here.
    """
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

    session_store = SessionStore(redis_url=REDIS_URL)
    conversation_context = ConversationContextStore(redis_url=REDIS_URL)
    tool_client = ToolRouterClient(base_url=TOOL_ROUTER_URL, tenant_id=tenant_id)
    remote_tools = await tool_client.fetch_gemini_tools()
    gemini_tools = build_gemini_tools(remote_tools)

    # PROP-602/docs/AGENCY_ONBOARDING.md Stage 2b: per-tenant branding
    # (tenant_settings.agency_name) takes priority over the process-level
    # AGENCY_NAME env var when DATABASE_URL is configured. Resolved before
    # _build_fallback_session_factory() below, so the fallback session (if
    # it's ever switched to mid-call) speaks under the same agency name as
    # the primary one, not a stale env-var default.
    agency_name = AGENCY_NAME
    if DATABASE_URL is not None:
        agency_name = await get_agency_name(DATABASE_URL, tenant_id, default=AGENCY_NAME)

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
            tenant_id=tenant_id,
            vad_detector=vad_detector,
            lk_api=lk_api,
            broker_phone_number=BROKER_PHONE_NUMBER,
            health_monitor=health_monitor,
            fallback_session_factory=fallback_session_factory,
            conversation_context=conversation_context,
        )
        await orchestrator.start()
        logger.info("Orchestrator running for room %r (tenant=%r)", room.name, tenant_id)

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
            logger.info("Call ended, cleaned up (room=%r tenant=%r)", room.name, tenant_id)
