"""
Closes infra/observability/SECURITY_AUDIT.md section 3's "no
service-to-service authentication" finding for this service: tool-router
is internal-only, with exactly one legitimate caller class (the
orchestrator, per the audit's own recommendation) -- unlike admin-api
(tenant-facing, one caller per tenant, see ../admin-api/auth.py's
per-tenant keys), a single shared secret is the right shape here.
"""

from __future__ import annotations

import hmac
import os

from fastapi import Header, HTTPException


async def require_internal_token(authorization: str | None = Header(default=None)) -> None:
    expected = os.environ.get("INTERNAL_SERVICE_TOKEN")
    if not expected:
        # Fail closed, not open -- an unconfigured token must not silently
        # grant access to anyone who can reach this port.
        raise HTTPException(status_code=500, detail="INTERNAL_SERVICE_TOKEN is not configured")
    if not authorization or not authorization.startswith("Bearer "):
        raise HTTPException(status_code=401, detail="Missing or malformed Authorization header")
    token = authorization.removeprefix("Bearer ")
    if not hmac.compare_digest(token, expected):
        raise HTTPException(status_code=401, detail="Invalid internal service token")
