"""
PROP-303: FastAPI Tool Router -- dispatches S2S function-call payloads
(tool name + args, matching Gemini's tool-calling protocol) to the right
handler and returns a JSON-serializable result.
"""

from __future__ import annotations

from contextlib import asynccontextmanager
from typing import Any

from fastapi import FastAPI, HTTPException
from pydantic import BaseModel, ValidationError

from db import close_pool, get_pool, tenant_connection
from tools.get_property_details import GetPropertyDetailsArgs, get_property_details
from tools.search_knowledge_base import SearchKnowledgeBaseArgs, search_knowledge_base
from tools.search_properties import SearchPropertiesArgs, search_properties
from tools.update_lead_qualification import UpdateLeadQualificationArgs, update_lead_qualification

TOOLS: dict[str, tuple[type[BaseModel], Any]] = {
    "search_properties": (SearchPropertiesArgs, search_properties),
    "get_property_details": (GetPropertyDetailsArgs, get_property_details),
    "search_knowledge_base": (SearchKnowledgeBaseArgs, search_knowledge_base),
    "update_lead_qualification": (UpdateLeadQualificationArgs, update_lead_qualification),
}

# Tools needing call-scoped context beyond tenant_id (who's calling, which
# lead row this call has already created) -- never exposed to Gemini's
# function schema, since Gemini has no reliable way to know either. Just
# update_lead_qualification today; a special case here rather than
# generic kwarg-forwarding plumbing for every tool, since only one needs it.
CONTEXT_ARG_TOOLS = {"update_lead_qualification"}


@asynccontextmanager
async def lifespan(app: FastAPI):
    await get_pool()
    yield
    await close_pool()


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
