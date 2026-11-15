"""
PROP-105 auto-dispatch: a long-running LiveKit Agent worker that gets a
job automatically dispatched to it for every new inbound call, instead of
a human running main.py by hand with an explicit room name.

This is the real production entrypoint once telephony exists; main.py
stays for isolating one specific test call by hand (see its own
docstring). Both share every bit of call-handling logic via
call_session.py -- this file is only "how does a job get triggered, and
which tenant does it belong to."

Needs `livekit-agents` installed (services/orchestrator/requirements.txt)
-- a separate package from `livekit`/`livekit-api`, which this codebase
already used directly. Verified against the installed package's actual
API (not assumed from docs, which show an older WorkerOptions/
request_fnc shape in some places) -- see services/orchestrator/README.md's
"Auto-dispatch" section for exactly what was checked and how.

Dispatch model: explicit, not automatic. A worker registered with a
non-empty `agent_name` (below) is only assigned a room when something
explicitly asks for it by that name -- LiveKit's own docs recommend this
over automatic "dispatch to every new room" for anything beyond
prototyping. For real inbound SIP calls, that "something" is
infra/livekit/dispatch-rule.json's `roomConfig.agents` entry, which must
name the exact same agent_name as below.

Per-tenant resolution uses the dialed E.164 DID in the SIP participant's
`sip.trunkPhoneNumber` attribute and the platform phone-number registry.
Unknown, inactive, or missing mappings end the room; there is no default
tenant fallback. The attribute's meaning is documented by LiveKit at
https://docs.livekit.io/reference/telephony/sip-participant.md.

Run:
    python worker.py dev     # connects to LIVEKIT_URL, waits for dispatched jobs
    (Ctrl+C to stop)

Testing without real telephony: create a room directly (e.g. via the
LiveKit server API, same mechanism test_orchestrator_live.py already
uses) with this agent_name requested, and confirm this process gets
dispatched into it automatically -- see
services/orchestrator/README.md's "Auto-dispatch" section for the exact
script used to verify this.
"""

from __future__ import annotations

import atexit
import logging
import os

from dotenv import load_dotenv

load_dotenv()

from livekit import agents, api, rtc

from db import terminate_pool
from call_session import (
    DATABASE_URL,
    LIVEKIT_API_KEY,
    LIVEKIT_API_SECRET,
    LIVEKIT_URL,
    run_orchestrator_on_room,
)
from metrics import start_metrics_server
from tenant_registry import resolve_tenant_by_phone

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("worker")
atexit.register(terminate_pool)

# Must match infra/livekit/dispatch-rule.json's roomConfig.agents[].agentName
# exactly, or real inbound calls will never reach this worker. Not read from
# an env var deliberately -- see the module docstring on why that ordering
# is fragile with a decorator that runs at import time.
AGENT_NAME = "propview-agent"
METRICS_PORT = int(os.environ.get("METRICS_PORT", "9090"))
SIP_DIALED_NUMBER_ATTRIBUTE = "sip.trunkPhoneNumber"


class TenantResolutionError(RuntimeError):
    pass


server = agents.AgentServer()


def _get_dialed_number(room: rtc.Room) -> str:
    sip_participants = [
        participant
        for participant in room.remote_participants.values()
        if participant.kind == rtc.ParticipantKind.PARTICIPANT_KIND_SIP
    ]
    if len(sip_participants) != 1:
        raise TenantResolutionError("Expected exactly one SIP caller in the dispatched room")

    dialed_number = sip_participants[0].attributes.get(SIP_DIALED_NUMBER_ATTRIBUTE)
    if not dialed_number:
        raise TenantResolutionError("LiveKit SIP participant has no dialed-number attribute")
    return dialed_number


async def _resolve_tenant_id(ctx: agents.JobContext) -> str:
    if not DATABASE_URL:
        raise TenantResolutionError("DATABASE_URL is required for inbound tenant resolution")

    dialed_number = _get_dialed_number(ctx.room)
    tenant_id = await resolve_tenant_by_phone(DATABASE_URL, dialed_number)
    if tenant_id is None:
        raise TenantResolutionError("No active tenant is mapped to this inbound number")
    return tenant_id


async def _end_unresolved_call(ctx: agents.JobContext) -> None:
    lk_api = api.LiveKitAPI(LIVEKIT_URL, LIVEKIT_API_KEY, LIVEKIT_API_SECRET)
    try:
        await lk_api.room.delete_room(api.DeleteRoomRequest(room=ctx.room.name))
    finally:
        await lk_api.aclose()


@server.rtc_session(agent_name=AGENT_NAME)
async def handle_call(ctx: agents.JobContext) -> None:
    await ctx.connect()
    try:
        tenant_id = await _resolve_tenant_id(ctx)
    except TenantResolutionError as exc:
        logger.error("Ending inbound call because tenant resolution failed: %s", exc)
        await _end_unresolved_call(ctx)
        return
    except Exception:
        logger.exception("Inbound tenant lookup failed; ending call rather than using a fallback tenant")
        await _end_unresolved_call(ctx)
        raise

    logger.info("Dispatched into room %r for tenant %r", ctx.room.name, tenant_id)
    await run_orchestrator_on_room(ctx.room, tenant_id)


if __name__ == "__main__":
    if METRICS_PORT:
        start_metrics_server(METRICS_PORT)
        logger.info("Prometheus metrics available at http://localhost:%d/metrics", METRICS_PORT)
    agents.cli.run_app(server)
