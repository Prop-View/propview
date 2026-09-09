"""
PROP-303: FastAPI Tool Router -- dispatches S2S function-call payloads
(tool name + args, matching Gemini's tool-calling protocol) to the right
handler and returns a JSON-serializable result.
"""

from __future__ import annotations

from contextlib import asynccontextmanager
from typing import Any

from dotenv import load_dotenv

load_dotenv()  # real gap found 2026-09-09: this was never called, so a
# .env file here was always silently ignored -- every env var (including
# ones read lazily by imported modules like crypto.py/sms_dispatch.py)
# had to be exported into the shell by hand instead. Must run before the
# tools.* imports below, since search_knowledge_base.py reads
# GEMINI_API_KEY at call time but tools.book_site_visit's own module-level
# code (sys.path wiring) still runs at import time regardless.

from fastapi import FastAPI, HTTPException  # noqa: E402
from pydantic import BaseModel, ValidationError  # noqa: E402

from db import close_pool, get_pool, tenant_connection  # noqa: E402
from redis_client import close_redis_client  # noqa: E402
from tools.book_site_visit import BookSiteVisitArgs, book_site_visit  # noqa: E402
from tools.check_calendar_slots import CheckCalendarSlotsArgs, check_calendar_slots  # noqa: E402
from tools.get_property_details import GetPropertyDetailsArgs, get_property_details  # noqa: E402
from tools.search_knowledge_base import SearchKnowledgeBaseArgs, search_knowledge_base  # noqa: E402
from tools.search_properties import SearchPropertiesArgs, search_properties  # noqa: E402
from tools.update_lead_qualification import UpdateLeadQualificationArgs, update_lead_qualification  # noqa: E402

TOOLS: dict[str, tuple[type[BaseModel], Any]] = {
    "search_properties": (SearchPropertiesArgs, search_properties),
    "get_property_details": (GetPropertyDetailsArgs, get_property_details),
    "search_knowledge_base": (SearchKnowledgeBaseArgs, search_knowledge_base),
    "update_lead_qualification": (UpdateLeadQualificationArgs, update_lead_qualification),
    "check_calendar_slots": (CheckCalendarSlotsArgs, check_calendar_slots),
    "book_site_visit": (BookSiteVisitArgs, book_site_visit),
}

# Tools needing call-scoped context beyond tenant_id (who's calling, which
# lead row this call has already created) -- never exposed to Gemini's
# function schema, since Gemini has no reliable way to know either. A
# special case here rather than generic kwarg-forwarding plumbing for
# every tool, since only these two need it.
CONTEXT_ARG_TOOLS = {"update_lead_qualification", "book_site_visit"}


@asynccontextmanager
async def lifespan(app: FastAPI):
    await get_pool()
    yield
    await close_pool()
    await close_redis_client()


app = FastAPI(title="Propview Tool Router", lifespan=lifespan)


class ToolCallRequest(BaseModel):
    name: str
    args: dict[str, Any] = {}
    tenant_id: str = "default"
    caller_phone_number: str | None = None
    lead_id: int | None = None


@app.post("/tools/call")
async def call_tool(request: ToolCallRequest):
    if request.name not in TOOLS:
        raise HTTPException(status_code=404, detail=f"Unknown tool: {request.name}")

    args_model, handler = TOOLS[request.name]
    try:
        args = args_model(**request.args)
    except ValidationError as exc:
        raise HTTPException(status_code=422, detail=exc.errors()) from exc

    extra_kwargs = {}
    if request.name in CONTEXT_ARG_TOOLS:
        extra_kwargs = {"caller_phone_number": request.caller_phone_number, "lead_id": request.lead_id}

    async with tenant_connection(request.tenant_id) as connection:
        try:
            result = await handler(connection, args, tenant_id=request.tenant_id, **extra_kwargs)
        except ValueError as exc:
            raise HTTPException(status_code=422, detail=str(exc)) from exc
    return {"name": request.name, "result": result}


@app.get("/tools/schema")
async def tools_schema():
    """JSON schemas for each tool's args -- the source for the Gemini
    FunctionDeclaration configs the orchestrator will register (Sprint 3/4
    wiring, not built yet)."""
    return {name: model.model_json_schema() for name, (model, _) in TOOLS.items()}


@app.get("/health")
async def health():
    return {"status": "ok"}
