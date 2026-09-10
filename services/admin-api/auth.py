"""
Closes infra/observability/SECURITY_AUDIT.md section 3's "no
service-to-service authentication" finding for this service: admin-api is
tenant-facing (one real caller per tenant, per the audit's own
recommendation), so this is per-tenant API keys, not a single shared
secret -- a shared secret would let any tenant's caller act as any other
tenant, since RLS only isolates tenants from each other, not
unauthenticated (or cross-tenant) callers from a tenant's data.

Keys are high-entropy random tokens (`generate_api_key`), so a fast
SHA-256 digest (`hash_key`) is the right hash here -- bcrypt/scrypt/argon2
exist to slow down brute-forcing a low-entropy *human* password, which
doesn't apply to a 256-bit random value. Only the hash is ever stored
(`tenant_settings.admin_api_key_hash`, see
../../db/migrations/006_admin_api_auth.sql); the plaintext key is shown
to the caller exactly once, at provisioning time, same as GitHub/Stripe
API tokens.
"""

from __future__ import annotations

import hashlib
import hmac
import os
import secrets

from fastapi import Header, HTTPException

from db import tenant_connection


def generate_api_key() -> str:
    return secrets.token_urlsafe(32)


def hash_key(key: str) -> str:
    return hashlib.sha256(key.encode()).hexdigest()


async def require_platform_token(authorization: str | None = Header(default=None)) -> None:
    """Gates tenant provisioning -- a platform-operator-only action (the
    real-world equivalent: whoever's running this SaaS platform onboards
    a new agency, see docs/AGENCY_ONBOARDING.md Stage 1). Deliberately a
    single shared secret, unlike per-tenant auth below: there is exactly
    one legitimate caller class here (platform ops tooling), not one per
    tenant."""
    expected = os.environ.get("PLATFORM_OPERATOR_TOKEN")
    if not expected:
        # Fail closed, not open -- an unconfigured token must not silently
        # grant provisioning access to anyone who can reach this port.
        raise HTTPException(status_code=500, detail="PLATFORM_OPERATOR_TOKEN is not configured")
    if not authorization or not authorization.startswith("Bearer "):
        raise HTTPException(status_code=401, detail="Missing or malformed Authorization header")
    token = authorization.removeprefix("Bearer ")
    if not hmac.compare_digest(token, expected):
        raise HTTPException(status_code=401, detail="Invalid platform operator token")


async def require_tenant_auth(tenant_id: str, authorization: str | None = Header(default=None)) -> None:
    """Gates every tenant-scoped admin-api route. The token must both be
    valid AND belong to *this* tenant_id -- a key provisioned for one
    tenant must not authenticate requests for another, which is the
    entire point of this being per-tenant rather than a shared secret."""
    if not authorization or not authorization.startswith("Bearer "):
        raise HTTPException(status_code=401, detail="Missing or malformed Authorization header")
    token = authorization.removeprefix("Bearer ")

    async with tenant_connection(tenant_id) as conn:
        row = await conn.fetchrow(
            "SELECT admin_api_key_hash FROM tenant_settings WHERE tenant_id = $1", tenant_id
        )
    # Same 401 either way (no provisioned key vs. wrong key) -- a 404-style
    # "tenant not found" here would let an attacker enumerate which
    # tenant_ids have been provisioned.
    if row is None or row["admin_api_key_hash"] is None:
        raise HTTPException(status_code=401, detail="Invalid credentials")
    if not hmac.compare_digest(hash_key(token), row["admin_api_key_hash"]):
        raise HTTPException(status_code=401, detail="Invalid credentials")
