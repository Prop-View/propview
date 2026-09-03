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

from db import close_pool, get_pool
from tools.get_property_details import GetPropertyDetailsArgs, get_property_details
from tools.search_properties import SearchPropertiesArgs, search_properties

TOOLS: dict[str, tuple[type[BaseModel], Any]] = {
    "search_properties": (SearchPropertiesArgs, search_properties),
    "get_property_details": (GetPropertyDetailsArgs, get_property_details),
}


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


@app.post("/tools/call")
async def call_tool(request: ToolCallRequest):
    if request.name not in TOOLS:
        raise HTTPException(status_code=404, detail=f"Unknown tool: {request.name}")

    args_model, handler = TOOLS[request.name]
    try:
        args = args_model(**request.args)
    except ValidationError as exc:
        raise HTTPException(status_code=422, detail=exc.errors()) from exc

    pool = await get_pool()
    result = await handler(pool, args, tenant_id=request.tenant_id)
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
