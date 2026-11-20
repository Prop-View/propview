"""Self-service agency signup, password sessions, and team management."""

from __future__ import annotations

import os
import re
from datetime import datetime, timedelta, timezone
from urllib.parse import quote

import asyncpg
from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field, field_validator

from account_auth import create_token, hash_password, hash_token, verify_password
from audit import write_audit
from auth import AuthPrincipal, require_owner, require_tenant_auth
from db import tenant_connection
from email_provider import EmailDeliveryError, send_email
from rate_limit import request_rate_limited, rate_limited

router = APIRouter()

_EMAIL_RE = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")
SESSION_TTL_SECONDS = int(os.environ.get("SESSION_TTL_SECONDS", "28800"))
if not 300 <= SESSION_TTL_SECONDS <= 86400:
    raise RuntimeError("SESSION_TTL_SECONDS must be between 300 and 86400")
SESSION_TTL = timedelta(seconds=SESSION_TTL_SECONDS)
_DUMMY_PASSWORD_HASH = hash_password("not-a-real-user-password")


def _validated_email(value: str) -> str:
    normalized = value.strip().lower()
    if len(normalized) > 320 or not _EMAIL_RE.fullmatch(normalized):
        raise ValueError("A valid email address is required")
    return normalized


def _dashboard_url(path: str, **params: str) -> str:
    base = os.environ.get("DASHBOARD_BASE_URL", "http://localhost:5173").rstrip("/")
    query = "&".join(f"{quote(key)}={quote(value)}" for key, value in params.items())
    return f"{base}{path}?{query}"


async def _send_account_email(recipient: str, subject: str, body: str) -> None:
    try:
        await send_email(recipient, subject, body)
    except EmailDeliveryError as exc:
        raise HTTPException(status_code=503, detail="Email delivery is unavailable") from exc


class SignupRequest(BaseModel):
    tenant_slug: str = Field(pattern=r"^[a-z0-9][a-z0-9-]{0,62}$")
    tenant_name: str = Field(min_length=1, max_length=200)
    owner_name: str = Field(min_length=1, max_length=200)
    email: str
    password: str = Field(min_length=12, max_length=256)

    @field_validator("email")
    @classmethod
    def validate_email(cls, value: str) -> str:
        return _validated_email(value)

    @field_validator("tenant_name", "owner_name")
    @classmethod
    def validate_names(cls, value: str) -> str:
        normalized = value.strip()
        if not normalized:
            raise ValueError("Name must not be blank")
        return normalized


class LoginRequest(BaseModel):
    tenant_slug: str = Field(pattern=r"^[a-z0-9][a-z0-9-]{0,62}$")
    email: str
    password: str = Field(min_length=1, max_length=256)

    @field_validator("email")
    @classmethod
    def validate_email(cls, value: str) -> str:
        return _validated_email(value)


class TokenRequest(BaseModel):
    token: str = Field(min_length=20, max_length=256)


class PasswordResetRequest(BaseModel):
    tenant_slug: str = Field(pattern=r"^[a-z0-9][a-z0-9-]{0,62}$")
    email: str

    @field_validator("email")
    @classmethod
    def validate_email(cls, value: str) -> str:
        return _validated_email(value)


class PasswordResetConfirmRequest(BaseModel):
    tenant_slug: str = Field(pattern=r"^[a-z0-9][a-z0-9-]{0,62}$")
    token: str = Field(min_length=20, max_length=256)
    password: str = Field(min_length=12, max_length=256)


class TeamInviteRequest(BaseModel):
    email: str
    display_name: str = Field(min_length=1, max_length=200)

    @field_validator("email")
    @classmethod
    def validate_email(cls, value: str) -> str:
        return _validated_email(value)

    @field_validator("display_name")
    @classmethod
    def validate_display_name(cls, value: str) -> str:
        normalized = value.strip()
        if not normalized:
            raise ValueError("Display name must not be blank")
        return normalized


class TeamAcceptRequest(BaseModel):
    token: str = Field(min_length=20, max_length=256)
    password: str = Field(min_length=12, max_length=256)


@router.post("/auth/signup", dependencies=[Depends(request_rate_limited(budget="signup"))])
async def signup(request: SignupRequest):
    tenant_id = request.tenant_slug
    token = create_token()
    expires_at = datetime.now(timezone.utc) + timedelta(hours=24)
    password_hash = hash_password(request.password)

    try:
        async with tenant_connection(tenant_id) as conn:
            await conn.execute(
                "SELECT public.platform_register_tenant($1, $2)",
                tenant_id,
                request.tenant_name.strip(),
            )
            user_id = await conn.fetchval(
                """
                INSERT INTO account_users
                    (tenant_id, email, display_name, password_hash, role)
                VALUES ($1, $2, $3, $4, 'owner')
                RETURNING id
                """,
                tenant_id,
                request.email,
                request.owner_name.strip(),
                password_hash,
            )
            await conn.execute(
                """
                INSERT INTO account_tokens (tenant_id, user_id, purpose, token_hash, expires_at)
                VALUES ($1, $2, 'email_verification', $3, $4)
                """,
                tenant_id,
                user_id,
                hash_token(token),
                expires_at,
            )
            await write_audit(
                conn, tenant_id, "account.signup_requested", user_id,
                "account_user", user_id, {"role": "owner"},
            )
    except asyncpg.UniqueViolationError as exc:
        raise HTTPException(status_code=409, detail="Tenant slug or account already exists") from exc

    verify_url = _dashboard_url("/verify-email", tenant=tenant_id, token=token)
    await _send_account_email(
        request.email,
        "Verify your Propview account",
        f"Hello {request.owner_name.strip()},\n\nVerify your email address: {verify_url}\n\nThis link expires in 24 hours.",
    )
    return {"tenant_slug": tenant_id, "status": "verification_required"}


@router.post("/auth/{tenant_id}/verify-email", dependencies=[Depends(request_rate_limited(budget="verify"))])
async def verify_email(tenant_id: str, request: TokenRequest):
    async with tenant_connection(tenant_id) as conn:
        row = await conn.fetchrow(
            """
            SELECT token.id AS token_id, token.user_id
            FROM account_tokens AS token
            JOIN account_users AS account
              ON account.id = token.user_id AND account.tenant_id = token.tenant_id
            WHERE token.tenant_id = $1 AND token.token_hash = $2
              AND token.purpose = 'email_verification'
              AND token.used_at IS NULL AND token.expires_at > now()
              AND account.email_verified_at IS NULL
            FOR UPDATE OF token
            """,
            tenant_id,
            hash_token(request.token),
        )
        if row is None:
            raise HTTPException(status_code=400, detail="Verification token is invalid or expired")
        await conn.execute(
            "UPDATE account_users SET email_verified_at = now(), updated_at = now() WHERE id = $1",
            row["user_id"],
        )
        await conn.execute("UPDATE account_tokens SET used_at = now() WHERE id = $1", row["token_id"])
        await conn.execute("SELECT public.platform_activate_tenant($1)", tenant_id)
        await write_audit(
            conn, tenant_id, "account.email_verified", row["user_id"],
            "account_user", row["user_id"],
        )
    return {"status": "verified"}


@router.post(
    "/auth/{tenant_id}/verification/resend",
    dependencies=[Depends(request_rate_limited(budget="verify"))],
)
async def resend_verification(tenant_id: str, request: PasswordResetRequest):
    async with tenant_connection(tenant_id) as conn:
        user = await conn.fetchrow(
            """
            SELECT id, display_name FROM account_users
            WHERE tenant_id = $1 AND email = $2 AND is_active
              AND email_verified_at IS NULL
            """,
            tenant_id,
            request.email,
        )
        token = create_token() if user is not None else None
        if user is not None:
            await conn.execute(
                """
                UPDATE account_tokens SET used_at = now()
                WHERE tenant_id = $1 AND user_id = $2
                  AND purpose = 'email_verification' AND used_at IS NULL
                """,
                tenant_id,
                user["id"],
            )
            await conn.execute(
                """
                INSERT INTO account_tokens (tenant_id, user_id, purpose, token_hash, expires_at)
                VALUES ($1, $2, 'email_verification', $3, now() + interval '24 hours')
                """,
                tenant_id,
                user["id"],
                hash_token(token),
            )
    if token is not None:
        verify_url = _dashboard_url("/verify-email", tenant=tenant_id, token=token)
        await _send_account_email(
            request.email,
            "Verify your Propview account",
            f"Hello {user['display_name']},\n\nVerify your email address: {verify_url}\n\nThis link expires in 24 hours.",
        )
    return {"status": "If verification is pending, a new email has been sent"}


@router.post("/auth/login", dependencies=[Depends(request_rate_limited(budget="login"))])
async def login(request: LoginRequest):
    async with tenant_connection(request.tenant_slug) as conn:
        user = await conn.fetchrow(
            """
            SELECT id, email, display_name, role, password_hash, is_active, email_verified_at
            FROM account_users
            WHERE tenant_id = $1 AND email = $2
            """,
            request.tenant_slug,
            request.email,
        )
        stored_hash = user["password_hash"] if user is not None else _DUMMY_PASSWORD_HASH
        password_matches = verify_password(stored_hash, request.password)
        if user is None or not password_matches:
            raise HTTPException(status_code=401, detail="Invalid email or password")
        if not user["is_active"]:
            raise HTTPException(status_code=403, detail="Account is disabled")
        if user["email_verified_at"] is None:
            raise HTTPException(status_code=403, detail="Verify your email before signing in")

        token = create_token()
        expires_at = datetime.now(timezone.utc) + SESSION_TTL
        await conn.execute(
            """
            INSERT INTO account_sessions (tenant_id, user_id, token_hash, expires_at)
            VALUES ($1, $2, $3, $4)
            """,
            request.tenant_slug,
            user["id"],
            hash_token(token),
            expires_at,
        )
        await write_audit(
            conn, request.tenant_slug, "account.login", user["id"],
            "account_user", user["id"],
        )
    return {
        "access_token": token,
        "token_type": "bearer",
        "expires_at": expires_at.isoformat(),
        "user": {
            "id": user["id"],
            "email": user["email"],
            "display_name": user["display_name"],
            "role": user["role"],
        },
    }


@router.post("/auth/password-reset/request", dependencies=[Depends(request_rate_limited(budget="password-reset"))])
async def request_password_reset(request: PasswordResetRequest):
    async with tenant_connection(request.tenant_slug) as conn:
        user = await conn.fetchrow(
            """
            SELECT id, display_name FROM account_users
            WHERE tenant_id = $1 AND email = $2 AND is_active
              AND email_verified_at IS NOT NULL
            """,
            request.tenant_slug,
            request.email,
        )
        if user is not None:
            token = create_token()
            expires_at = datetime.now(timezone.utc) + timedelta(minutes=30)
            await conn.execute(
                """
                INSERT INTO account_tokens (tenant_id, user_id, purpose, token_hash, expires_at)
                VALUES ($1, $2, 'password_reset', $3, $4)
                """,
                request.tenant_slug,
                user["id"],
                hash_token(token),
                expires_at,
            )
            await write_audit(
                conn, request.tenant_slug, "account.password_reset_requested",
                user["id"], "account_user", user["id"],
            )
        else:
            token = None

    if token is not None:
        reset_url = _dashboard_url(
            "/reset-password", tenant=request.tenant_slug, token=token
        )
        await _send_account_email(
            request.email,
            "Reset your Propview password",
            f"Reset your password: {reset_url}\n\nThis link expires in 30 minutes.",
        )
    return {"status": "If the account exists, a reset email has been sent"}


@router.post("/auth/password-reset/confirm", dependencies=[Depends(request_rate_limited(budget="password-reset"))])
async def confirm_password_reset(request: PasswordResetConfirmRequest):
    async with tenant_connection(request.tenant_slug) as conn:
        row = await conn.fetchrow(
            """
            SELECT token.id AS token_id, token.user_id
            FROM account_tokens AS token
            JOIN account_users AS account
              ON account.id = token.user_id AND account.tenant_id = token.tenant_id
            WHERE token.tenant_id = $1 AND token.token_hash = $2
              AND token.purpose = 'password_reset'
              AND token.used_at IS NULL AND token.expires_at > now()
              AND account.is_active AND account.email_verified_at IS NOT NULL
            FOR UPDATE OF token
            """,
            request.tenant_slug,
            hash_token(request.token),
        )
        if row is None:
            raise HTTPException(status_code=400, detail="Password reset token is invalid or expired")
        await conn.execute(
            "UPDATE account_users SET password_hash = $1, updated_at = now() WHERE id = $2",
            hash_password(request.password),
            row["user_id"],
        )
        await conn.execute(
            """
            UPDATE account_tokens SET used_at = now()
            WHERE tenant_id = $1 AND user_id = $2
              AND purpose = 'password_reset' AND used_at IS NULL
            """,
            request.tenant_slug,
            row["user_id"],
        )
        await conn.execute(
            "UPDATE account_sessions SET revoked_at = now() WHERE tenant_id = $1 AND user_id = $2 AND revoked_at IS NULL",
            request.tenant_slug,
            row["user_id"],
        )
        await write_audit(
            conn, request.tenant_slug, "account.password_reset",
            row["user_id"], "account_user", row["user_id"],
        )
    return {"status": "password_updated"}


@router.post("/auth/{tenant_id}/logout")
async def logout(
    tenant_id: str,
    principal: AuthPrincipal = Depends(require_tenant_auth),
):
    if principal.auth_type != "session" or principal.user_id is None:
        raise HTTPException(status_code=400, detail="Only browser sessions can be logged out")
    async with tenant_connection(tenant_id) as conn:
        await conn.execute(
            """
            UPDATE account_sessions
            SET revoked_at = now()
            WHERE tenant_id = $1 AND token_hash = $2 AND revoked_at IS NULL
            """,
            tenant_id,
            principal.session_token_hash,
        )
    return {"status": "signed_out"}


@router.get("/auth/{tenant_id}/me")
async def me(
    tenant_id: str,
    principal: AuthPrincipal = Depends(require_tenant_auth),
):
    if principal.auth_type != "session" or principal.user_id is None:
        raise HTTPException(status_code=401, detail="Browser session required")
    async with tenant_connection(tenant_id) as conn:
        row = await conn.fetchrow(
            """
            SELECT id, email, display_name, role
            FROM account_users WHERE tenant_id = $1 AND id = $2 AND is_active
            """,
            tenant_id,
            principal.user_id,
        )
    if row is None:
        raise HTTPException(status_code=401, detail="Browser session is no longer active")
    return dict(row)


@router.get(
    "/admin/tenants/{tenant_id}/team",
    dependencies=[Depends(require_owner), Depends(rate_limited(budget="team-read"))],
)
async def list_team(tenant_id: str):
    async with tenant_connection(tenant_id) as conn:
        rows = await conn.fetch(
            """
            SELECT id, email, display_name, role, is_active, email_verified_at, created_at
            FROM account_users WHERE tenant_id = $1 ORDER BY created_at, id
            """,
            tenant_id,
        )
    return {"items": [dict(row) for row in rows]}


@router.post(
    "/admin/tenants/{tenant_id}/team/invitations",
    dependencies=[Depends(require_owner), Depends(rate_limited(budget="team-write"))],
)
async def invite_team_member(
    tenant_id: str,
    request: TeamInviteRequest,
    principal: AuthPrincipal = Depends(require_owner),
):
    token = create_token()
    expires_at = datetime.now(timezone.utc) + timedelta(days=7)
    temporary_hash = hash_password(create_token())
    try:
        async with tenant_connection(tenant_id) as conn:
            user_id = await conn.fetchval(
                """
                INSERT INTO account_users (tenant_id, email, display_name, password_hash, role)
                VALUES ($1, $2, $3, $4, 'agent')
                RETURNING id
                """,
                tenant_id,
                request.email,
                request.display_name.strip(),
                temporary_hash,
            )
            await conn.execute(
                """
                INSERT INTO account_tokens (tenant_id, user_id, purpose, token_hash, expires_at)
                VALUES ($1, $2, 'team_invite', $3, $4)
                """,
                tenant_id,
                user_id,
                hash_token(token),
                expires_at,
            )
            await write_audit(
                conn, tenant_id, "team.invitation_created", principal.user_id,
                "account_user", user_id, {"role": "agent"},
            )
    except asyncpg.UniqueViolationError as exc:
        raise HTTPException(status_code=409, detail="An account with this email already exists") from exc

    invite_url = _dashboard_url("/accept-invitation", tenant=tenant_id, token=token)
    await _send_account_email(
        request.email,
        "You have been invited to Propview",
        f"Hello {request.display_name.strip()},\n\nAccept your invitation: {invite_url}\n\nThis link expires in 7 days.",
    )
    return {"user_id": user_id, "status": "invitation_sent"}


@router.post(
    "/admin/tenants/{tenant_id}/team/{user_id}/resend-invitation",
    dependencies=[Depends(require_owner), Depends(rate_limited(budget="team-write"))],
)
async def resend_team_invitation(
    tenant_id: str,
    user_id: int,
    principal: AuthPrincipal = Depends(require_owner),
):
    token = create_token()
    expires_at = datetime.now(timezone.utc) + timedelta(days=7)
    async with tenant_connection(tenant_id) as conn:
        user = await conn.fetchrow(
            """
            SELECT email, display_name FROM account_users
            WHERE tenant_id = $1 AND id = $2 AND role = 'agent'
              AND is_active AND email_verified_at IS NULL
            """,
            tenant_id,
            user_id,
        )
        if user is None:
            raise HTTPException(status_code=404, detail="Pending team invitation not found")
        await conn.execute(
            """
            UPDATE account_tokens SET used_at = now()
            WHERE tenant_id = $1 AND user_id = $2
              AND purpose = 'team_invite' AND used_at IS NULL
            """,
            tenant_id,
            user_id,
        )
        await conn.execute(
            """
            INSERT INTO account_tokens (tenant_id, user_id, purpose, token_hash, expires_at)
            VALUES ($1, $2, 'team_invite', $3, $4)
            """,
            tenant_id,
            user_id,
            hash_token(token),
            expires_at,
        )
        await write_audit(
            conn, tenant_id, "team.invitation_resent", principal.user_id,
            "account_user", user_id,
        )
    invite_url = _dashboard_url("/accept-invitation", tenant=tenant_id, token=token)
    await _send_account_email(
        user["email"],
        "You have been invited to Propview",
        f"Hello {user['display_name']},\n\nAccept your invitation: {invite_url}\n\nThis link expires in 7 days.",
    )
    return {"user_id": user_id, "status": "invitation_sent"}


@router.post(
    "/auth/{tenant_id}/team/accept",
    dependencies=[Depends(request_rate_limited(budget="team-accept"))],
)
async def accept_team_invitation(tenant_id: str, request: TeamAcceptRequest):
    async with tenant_connection(tenant_id) as conn:
        row = await conn.fetchrow(
            """
            SELECT token.id AS token_id, token.user_id
            FROM account_tokens AS token
            JOIN account_users AS account
              ON account.id = token.user_id AND account.tenant_id = token.tenant_id
            WHERE token.tenant_id = $1 AND token.token_hash = $2
              AND token.purpose = 'team_invite'
              AND token.used_at IS NULL AND token.expires_at > now()
              AND account.is_active AND account.email_verified_at IS NULL
            FOR UPDATE OF token
            """,
            tenant_id,
            hash_token(request.token),
        )
        if row is None:
            raise HTTPException(status_code=400, detail="Invitation token is invalid or expired")
        await conn.execute(
            """
            UPDATE account_users
            SET password_hash = $1, email_verified_at = now(), updated_at = now()
            WHERE tenant_id = $2 AND id = $3
            """,
            hash_password(request.password),
            tenant_id,
            row["user_id"],
        )
        await conn.execute("UPDATE account_tokens SET used_at = now() WHERE id = $1", row["token_id"])
        await write_audit(
            conn, tenant_id, "team.invitation_accepted", row["user_id"],
            "account_user", row["user_id"],
        )
    return {"status": "accepted"}


@router.delete(
    "/admin/tenants/{tenant_id}/team/{user_id}",
    dependencies=[Depends(require_owner), Depends(rate_limited(budget="team-write"))],
)
async def deactivate_team_member(
    tenant_id: str,
    user_id: int,
    principal: AuthPrincipal = Depends(require_owner),
):
    if user_id == principal.user_id:
        raise HTTPException(status_code=400, detail="Owners cannot deactivate their own account")
    async with tenant_connection(tenant_id) as conn:
        target = await conn.fetchrow(
            "SELECT id, role FROM account_users WHERE tenant_id = $1 AND id = $2 AND is_active",
            tenant_id,
            user_id,
        )
        if target is None:
            raise HTTPException(status_code=404, detail="Team member not found")
        if target["role"] == "owner":
            raise HTTPException(status_code=400, detail="Owner accounts cannot be deactivated here")
        await conn.execute(
            "UPDATE account_users SET is_active = FALSE, updated_at = now() WHERE tenant_id = $1 AND id = $2",
            tenant_id,
            user_id,
        )
        await conn.execute(
            "UPDATE account_sessions SET revoked_at = now() WHERE tenant_id = $1 AND user_id = $2 AND revoked_at IS NULL",
            tenant_id,
            user_id,
        )
        await write_audit(
            conn, tenant_id, "team.member_deactivated", principal.user_id,
            "account_user", user_id,
        )
    return {"status": "deactivated"}
