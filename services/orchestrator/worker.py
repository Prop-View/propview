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

Per-tenant resolution: a dispatch job can carry a freeform metadata
string, set by whichever dispatch rule routed the call here (or an
explicit CreateDispatch call, or a RoomAgentDispatch token entry) --
read via `ctx.job.metadata` below. This replaces main.py's single
process-wide TENANT_ID env var, which can't vary per call: a real
deployment serving multiple agencies needs each tenant's own dispatch
rule carrying that tenant's tenant_id as metadata (see
infra/livekit/dispatch-rule.json and its README for the one-rule-per-tenant
pattern this implies).

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

import json
import logging
import os

from dotenv import load_dotenv
from livekit import agents

from call_session import run_orchestrator_on_room
from metrics import start_metrics_server

load_dotenv()  # before the decorator below runs -- see the module docstring's ordering note

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("worker")

# Must match infra/livekit/dispatch-rule.json's roomConfig.agents[].agentName
# exactly, or real inbound calls will never reach this worker. Not read from
# an env var deliberately -- see the module docstring on why that ordering
# is fragile with a decorator that runs at import time.
AGENT_NAME = "propview-agent"
DEFAULT_TENANT_ID = os.environ.get("TENANT_ID", "default")
METRICS_PORT = int(os.environ.get("METRICS_PORT", "9090"))

server = agents.AgentServer()


def _resolve_tenant_id(ctx: agents.JobContext) -> str:
    """Per-call tenant resolution -- see the module docstring's "Per-tenant
    resolution" section. Falls back to DEFAULT_TENANT_ID (same default
    main.py uses) if metadata is empty/unset (e.g. a dev-time test room
    created without it) or isn't valid JSON, so a misconfigured dispatch
    rule degrades to "handled as the default tenant," not a crashed job."""
    if not ctx.job.metadata:
        return DEFAULT_TENANT_ID
    try:
        data = json.loads(ctx.job.metadata)
    except (json.JSONDecodeError, TypeError):
        logger.warning("Job metadata isn't valid JSON, falling back to tenant %r: %r", DEFAULT_TENANT_ID, ctx.job.metadata)
        return DEFAULT_TENANT_ID
    return data.get("tenant_id", DEFAULT_TENANT_ID)


@server.rtc_session(agent_name=AGENT_NAME)
async def handle_call(ctx: agents.JobContext) -> None:
    await ctx.connect()
    tenant_id = _resolve_tenant_id(ctx)
    logger.info("Dispatched into room %r for tenant %r", ctx.room.name, tenant_id)
    await run_orchestrator_on_room(ctx.room, tenant_id)


if __name__ == "__main__":
    if METRICS_PORT:
        start_metrics_server(METRICS_PORT)
        logger.info("Prometheus metrics available at http://localhost:%d/metrics", METRICS_PORT)
    agents.cli.run_app(server)
