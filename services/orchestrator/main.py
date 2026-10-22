"""
Sprint 1 entrypoint: runs one CallOrchestrator against a LiveKit room.

Deliberately the "manual" path -- connects to one named room and bridges
it to Gemini for the life of that call, started by hand with an explicit
room name. Kept alongside worker.py (the auto-dispatched entrypoint that
replaces "started by hand" with "triggered automatically on every new
inbound call") rather than replaced by it: isolating one specific room is
genuinely useful for debugging a single test call without a real SIP
trunk or dispatch rule in the way. Both share every bit of actual
call-handling logic via call_session.py -- this file is now just "how do
we get a connected room and a tenant_id," nothing more.

Usage:
    python main.py <room-name>
"""

from __future__ import annotations

import asyncio
import logging
import os
import sys

from dotenv import load_dotenv
from livekit import api, rtc

from call_session import LIVEKIT_API_KEY, LIVEKIT_API_SECRET, LIVEKIT_URL, run_orchestrator_on_room
from metrics import start_metrics_server

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("main")

AGENT_IDENTITY = "ai-agent"
TENANT_ID = os.environ.get("TENANT_ID", "default")
# PROP-603 -- set to 0 to disable the /metrics endpoint entirely (e.g. running
# many of these processes locally at once, where each would try to bind the same port).
METRICS_PORT = int(os.environ.get("METRICS_PORT", "9090"))


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
    await room.connect(LIVEKIT_URL, make_token(room_name))
    logger.info("Agent joined room %r", room_name)
    await run_orchestrator_on_room(room, TENANT_ID)


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
