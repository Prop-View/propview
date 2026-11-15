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
from dataclasses import dataclass

from fastapi import Depends, Header, HTTPException

from db import tenant_connection


@dataclass(frozen=True)
class AuthPrincipal:
    tenant_id: str
    user_id: int | None
    role: str | None
    auth_type: str
    session_token_hash: str | None = None


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


async def require_tenant_auth(
    tenant_id: str, authorization: str | None = Header(default=None)
) -> AuthPrincipal:
    """Gates every tenant-scoped admin-api route. The token must both be
    valid AND belong to *this* tenant_id -- a key provisioned for one
    tenant must not authenticate requests for another, which is the
    entire point of this being per-tenant rather than a shared secret."""
    if not authorization or not authorization.startswith("Bearer "):
        raise HTTPException(status_code=401, detail="Missing or malformed Authorization header")
    token = authorization.removeprefix("Bearer ")

    async with tenant_connection(tenant_id) as conn:
        session = await conn.fetchrow(
            """
            SELECT s.user_id, u.role
            FROM account_sessions AS s
            JOIN account_users AS u
              ON u.id = s.user_id AND u.tenant_id = s.tenant_id
            WHERE s.tenant_id = $1 AND s.token_hash = $2
              AND s.revoked_at IS NULL AND s.expires_at > now()
              AND u.is_active AND u.email_verified_at IS NOT NULL
            """,
            tenant_id,
            hashlib.sha256(token.encode()).hexdigest(),
        )
        if session is not None:
            return AuthPrincipal(
                tenant_id=tenant_id,
                user_id=session["user_id"],
                role=session["role"],
                auth_type="session",
                session_token_hash=hashlib.sha256(token.encode()).hexdigest(),
            )
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
    return AuthPrincipal(tenant_id=tenant_id, user_id=None, role=None, auth_type="api_key")


async def require_owner(principal: AuthPrincipal = Depends(require_tenant_auth)) -> AuthPrincipal:
    """Require an authenticated human owner for account administration."""
    if principal.auth_type != "session" or principal.role != "owner":
        raise HTTPException(status_code=403, detail="Owner session required")
    return principal


async def require_machine_api_key(
    principal: AuthPrincipal = Depends(require_tenant_auth),
) -> AuthPrincipal:
    """Keep long-lived API keys off browser-only credential read routes."""
    if principal.auth_type != "api_key":
        raise HTTPException(status_code=403, detail="Machine API key required")
    return principal


async def require_owner_or_machine(
    principal: AuthPrincipal = Depends(require_tenant_auth),
) -> AuthPrincipal:
    """Allow an agency owner or machine integration, but not an agent session."""
    if principal.auth_type == "api_key":
        return principal
    if principal.role != "owner":
        raise HTTPException(status_code=403, detail="Owner session required")
    return principal
