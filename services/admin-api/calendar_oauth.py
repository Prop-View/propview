"""Google Calendar OAuth connect flow with one-time, tenant-bound state."""

from __future__ import annotations

import hashlib
import hmac
import json
import os
import re
import time
from urllib.parse import urlencode

import httpx
from fastapi import APIRouter, Depends, HTTPException, Query
from fastapi.responses import RedirectResponse

from account_auth import hash_token
from audit import write_audit
from auth import AuthPrincipal, require_owner
from crypto import encrypt
from db import tenant_connection
from rate_limit import rate_limited, request_rate_limited

router = APIRouter()
_SLUG_RE = re.compile(r"^[a-z0-9][a-z0-9-]{0,62}$")
_GOOGLE_AUTH_ENDPOINT = "https://accounts.google.com/o/oauth2/v2/auth"
_GOOGLE_TOKEN_ENDPOINT = "https://oauth2.googleapis.com/token"
_CALENDAR_SCOPE = "https://www.googleapis.com/auth/calendar.events"


@router.get(
    "/admin/tenants/{tenant_id}/calendar/google/status",
    dependencies=[Depends(require_owner), Depends(rate_limited(budget="calendar-oauth"))],
)
async def google_calendar_status(tenant_id: str):
    async with tenant_connection(tenant_id) as conn:
        row = await conn.fetchrow(
            "SELECT calendar_provider, encrypted_calendar_credentials IS NOT NULL AS connected FROM tenant_settings WHERE tenant_id = $1",
            tenant_id,
        )
    return {
        "provider": row["calendar_provider"] if row else None,
        "connected": bool(row and row["connected"]),
    }


def _oauth_config() -> tuple[str, str, str]:
    client_id = os.environ.get("GOOGLE_OAUTH_CLIENT_ID")
    client_secret = os.environ.get("GOOGLE_OAUTH_CLIENT_SECRET")
    redirect_uri = os.environ.get("GOOGLE_OAUTH_REDIRECT_URI")
    if not client_id or not client_secret or not redirect_uri:
        raise HTTPException(status_code=503, detail="Google Calendar OAuth is not configured")
    return client_id, client_secret, redirect_uri


def _state_secret() -> bytes:
    secret = os.environ.get("GOOGLE_OAUTH_STATE_SECRET")
    if not secret:
        raise HTTPException(status_code=503, detail="Google OAuth state signing is not configured")
    return secret.encode("utf-8")


def _make_state(tenant_id: str, expires_at: int) -> str:
    payload = f"{tenant_id}.{expires_at}.{hashlib.sha256(os.urandom(32)).hexdigest()}"
    signature = hmac.new(_state_secret(), payload.encode(), hashlib.sha256).hexdigest()
    return f"{payload}.{signature}"


def _read_state(state: str) -> tuple[str, int]:
    try:
        tenant_id, expiry, nonce, signature = state.split(".", maxsplit=3)
        expires_at = int(expiry)
    except (ValueError, TypeError) as exc:
        raise HTTPException(status_code=400, detail="Invalid OAuth state") from exc
    payload = f"{tenant_id}.{expiry}.{nonce}"
    expected = hmac.new(_state_secret(), payload.encode(), hashlib.sha256).hexdigest()
    if (
        not _SLUG_RE.fullmatch(tenant_id)
        or expires_at < int(time.time())
        or not hmac.compare_digest(signature, expected)
    ):
        raise HTTPException(status_code=400, detail="Invalid or expired OAuth state")
    return tenant_id, expires_at


@router.get(
    "/admin/tenants/{tenant_id}/calendar/google/connect",
    dependencies=[Depends(require_owner), Depends(rate_limited(budget="calendar-oauth"))],
)
async def start_google_calendar_connect(
    tenant_id: str,
    principal: AuthPrincipal = Depends(require_owner),
):
    client_id, _, redirect_uri = _oauth_config()
    expires_at = int(time.time()) + 600
    state = _make_state(tenant_id, expires_at)
    async with tenant_connection(tenant_id) as conn:
        await conn.execute(
            """
            INSERT INTO tenant_settings
                (tenant_id, google_oauth_state_hash, google_oauth_state_expires_at, updated_at)
            VALUES ($1, $2, to_timestamp($3), now())
            ON CONFLICT (tenant_id) DO UPDATE SET
                google_oauth_state_hash = EXCLUDED.google_oauth_state_hash,
                google_oauth_state_expires_at = EXCLUDED.google_oauth_state_expires_at,
                updated_at = now()
            """,
            tenant_id,
            hash_token(state),
            expires_at,
        )
        await write_audit(
            conn, tenant_id, "calendar.oauth_started", principal.user_id,
            "tenant_settings", tenant_id,
        )

    authorization_url = _GOOGLE_AUTH_ENDPOINT + "?" + urlencode(
        {
            "client_id": client_id,
            "redirect_uri": redirect_uri,
            "response_type": "code",
            "scope": _CALENDAR_SCOPE,
            "access_type": "offline",
            "prompt": "consent",
            "include_granted_scopes": "true",
            "state": state,
        }
    )
    return {"authorization_url": authorization_url}


@router.get(
    "/auth/calendar/google/callback",
    dependencies=[Depends(request_rate_limited(budget="calendar-oauth-callback"))],
)
async def google_calendar_callback(
    state: str = Query(min_length=30, max_length=512),
    code: str | None = Query(default=None, max_length=4096),
    error: str | None = Query(default=None, max_length=256),
):
    tenant_id, expires_at = _read_state(state)
    if error:
        raise HTTPException(status_code=400, detail="Google Calendar authorization was not completed")
    if not code:
        raise HTTPException(status_code=400, detail="Google did not return an authorization code")

    async with tenant_connection(tenant_id) as conn:
        consumed = await conn.fetchval(
            """
            UPDATE tenant_settings
            SET google_oauth_state_hash = NULL,
                google_oauth_state_expires_at = NULL,
                updated_at = now()
            WHERE tenant_id = $1 AND google_oauth_state_hash = $2
              AND google_oauth_state_expires_at > now()
              AND google_oauth_state_expires_at <= to_timestamp($3)
            RETURNING tenant_id
            """,
            tenant_id,
            hash_token(state),
            expires_at,
        )
    if consumed is None:
        raise HTTPException(status_code=400, detail="OAuth state was already used or expired")

    client_id, client_secret, redirect_uri = _oauth_config()
    try:
        async with httpx.AsyncClient(timeout=10.0, follow_redirects=False) as client:
            response = await client.post(
                _GOOGLE_TOKEN_ENDPOINT,
                data={
                    "code": code,
                    "client_id": client_id,
                    "client_secret": client_secret,
                    "redirect_uri": redirect_uri,
                    "grant_type": "authorization_code",
                },
                headers={"Accept": "application/json"},
            )
    except httpx.TimeoutException as exc:
        raise HTTPException(status_code=502, detail="Google OAuth token exchange timed out") from exc
    except httpx.RequestError as exc:
        raise HTTPException(status_code=502, detail="Google OAuth token exchange failed") from exc
    if response.is_error:
        raise HTTPException(status_code=502, detail="Google rejected the OAuth token exchange")
    try:
        credentials = response.json()
    except ValueError as exc:
        raise HTTPException(status_code=502, detail="Google returned an invalid token response") from exc
    if not isinstance(credentials, dict) or not credentials.get("refresh_token"):
        raise HTTPException(
            status_code=400,
            detail="Google did not return a refresh token; reconnect and grant offline access",
        )

    encrypted_credentials = encrypt(json.dumps(credentials))
    async with tenant_connection(tenant_id) as conn:
        await conn.execute(
            """
            INSERT INTO tenant_settings
                (tenant_id, calendar_provider, encrypted_calendar_credentials, updated_at)
            VALUES ($1, 'google_calendar', $2, now())
            ON CONFLICT (tenant_id) DO UPDATE SET
                calendar_provider = EXCLUDED.calendar_provider,
                encrypted_calendar_credentials = EXCLUDED.encrypted_calendar_credentials,
                updated_at = now()
            """,
            tenant_id,
            encrypted_credentials,
        )
        await write_audit(
            conn, tenant_id, "calendar.oauth_connected", None,
            "tenant_settings", tenant_id, {"provider": "google_calendar"},
        )

    dashboard = os.environ.get("DASHBOARD_BASE_URL", "http://localhost:5173").rstrip("/")
    return RedirectResponse(f"{dashboard}/settings?calendar=connected", status_code=303)
