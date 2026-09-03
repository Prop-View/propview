"""
Wires the orchestrator to the Tool Router (../tool-router/): builds Gemini
FunctionDeclarations from its /tools/schema endpoint (single source of
truth -- the Pydantic models in tool-router already define the schema,
this doesn't hand-duplicate them), and executes calls against /tools/call.
"""

from __future__ import annotations

import httpx
from google.genai import types


class ToolRouterClient:
    def __init__(self, base_url: str = "http://localhost:8000", tenant_id: str = "default"):
        self._tenant_id = tenant_id
        self._client = httpx.AsyncClient(base_url=base_url, timeout=10.0)

    async def fetch_gemini_tools(self) -> list[types.Tool]:
        resp = await self._client.get("/tools/schema")
        resp.raise_for_status()
        schemas = resp.json()

        declarations = [
            types.FunctionDeclaration(name=name, parameters_json_schema=schema)
            for name, schema in schemas.items()
        ]
        return [types.Tool(function_declarations=declarations)]

    async def call_tool(
        self, name: str, args: dict, caller_phone_number: str | None = None, lead_id: int | None = None
    ) -> dict:
        """`caller_phone_number`/`lead_id` are call-scoped context, not
        something Gemini supplies -- like `tenant_id`, they're bound at the
        orchestrator layer (see orchestrator.py's _handle_tool_call) and
        only actually used server-side by update_lead_qualification
        (PROP-402); harmless no-ops for every other tool."""
        resp = await self._client.post(
            "/tools/call",
            json={
                "name": name,
                "args": args,
                "tenant_id": self._tenant_id,
                "caller_phone_number": caller_phone_number,
                "lead_id": lead_id,
            },
        )
        resp.raise_for_status()
        return resp.json()["result"]

    async def aclose(self) -> None:
        await self._client.aclose()
