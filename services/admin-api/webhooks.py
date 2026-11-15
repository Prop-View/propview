"""Tenant webhook configuration API; signing secrets are only shown once."""

from __future__ import annotations

import ipaddress
import secrets
import socket
from urllib.parse import urlparse

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, Field, field_validator

from audit import write_audit
from auth import AuthPrincipal, require_owner
from crypto import encrypt
from db import tenant_connection
from rate_limit import rate_limited

router = APIRouter()
SUPPORTED_EVENTS = {
    "lead.created",
    "lead.qualified",
    "appointment.booked",
    "call.completed",
}


def validate_webhook_url(value: str) -> str:
    parsed = urlparse(value)
    if (
        parsed.scheme != "https"
        or not parsed.hostname
        or parsed.username is not None
        or parsed.password is not None
        or parsed.fragment
    ):
        raise ValueError("Webhook URL must be an HTTPS URL without credentials or a fragment")
    try:
        addresses = {
            ipaddress.ip_address(result[4][0])
            for result in socket.getaddrinfo(parsed.hostname, parsed.port or 443)
        }
    except OSError as exc:
        raise ValueError("Webhook host could not be resolved") from exc
    if not addresses or any(not address.is_global for address in addresses):
        raise ValueError("Webhook host must resolve only to public IP addresses")
    return value


class WebhookCreateRequest(BaseModel):
    target_url: str = Field(min_length=10, max_length=2048)
    events: list[str] = Field(min_length=1, max_length=4)

    @field_validator("target_url")
    @classmethod
    def validate_target_url(cls, value: str) -> str:
        return validate_webhook_url(value)

    @field_validator("events")
    @classmethod
    def validate_events(cls, value: list[str]) -> list[str]:
        if len(set(value)) != len(value) or not set(value).issubset(SUPPORTED_EVENTS):
            raise ValueError("Webhook event list contains duplicates or unsupported events")
        return value


class WebhookUpdateRequest(BaseModel):
    target_url: str | None = Field(default=None, min_length=10, max_length=2048)
    events: list[str] | None = Field(default=None, min_length=1, max_length=4)
    is_enabled: bool | None = None

    @field_validator("target_url")
    @classmethod
    def validate_target_url(cls, value: str | None) -> str | None:
        return validate_webhook_url(value) if value is not None else None

    @field_validator("events")
    @classmethod
    def validate_events(cls, value: list[str] | None) -> list[str] | None:
        if value is not None and (
            len(set(value)) != len(value) or not set(value).issubset(SUPPORTED_EVENTS)
        ):
            raise ValueError("Webhook event list contains duplicates or unsupported events")
        return value


@router.get(
    "/admin/tenants/{tenant_id}/webhooks",
    dependencies=[Depends(require_owner), Depends(rate_limited(budget="webhook-read"))],
)
async def list_webhooks(tenant_id: str):
    async with tenant_connection(tenant_id) as conn:
        rows = await conn.fetch(
            """
            SELECT hook.id, hook.target_url, hook.events, hook.is_enabled,
                   hook.created_at, hook.updated_at,
                   count(delivery.id)::int AS delivery_count,
                   count(delivery.id) FILTER (WHERE delivery.status = 'failed')::int AS failed_count
            FROM tenant_webhooks AS hook
            LEFT JOIN webhook_deliveries AS delivery
              ON delivery.webhook_id = hook.id AND delivery.tenant_id = hook.tenant_id
            WHERE hook.tenant_id = $1
            GROUP BY hook.id
            ORDER BY hook.created_at DESC
            """,
            tenant_id,
        )
    return {"items": [dict(row) for row in rows]}


@router.post(
    "/admin/tenants/{tenant_id}/webhooks",
    dependencies=[Depends(require_owner), Depends(rate_limited(budget="webhook-write"))],
)
async def create_webhook(
    tenant_id: str,
    request: WebhookCreateRequest,
    principal: AuthPrincipal = Depends(require_owner),
):
    signing_secret = secrets.token_urlsafe(32)
    async with tenant_connection(tenant_id) as conn:
        webhook_id = await conn.fetchval(
            """
            INSERT INTO tenant_webhooks
                (tenant_id, target_url, encrypted_signing_secret, events)
            VALUES ($1, $2, $3, $4)
            RETURNING id
            """,
            tenant_id,
            request.target_url,
            encrypt(signing_secret),
            request.events,
        )
        await write_audit(
            conn, tenant_id, "webhook.created", principal.user_id,
            "tenant_webhook", webhook_id, {"events": request.events},
        )
    return {"id": webhook_id, "signing_secret": signing_secret}


@router.get(
    "/admin/tenants/{tenant_id}/webhooks/{webhook_id}/deliveries",
    dependencies=[Depends(require_owner), Depends(rate_limited(budget="webhook-read"))],
)
async def list_webhook_deliveries(
    tenant_id: str,
    webhook_id: int,
    limit: int = Query(default=50, ge=1, le=200),
):
    async with tenant_connection(tenant_id) as conn:
        webhook_exists = await conn.fetchval(
            "SELECT EXISTS(SELECT 1 FROM tenant_webhooks WHERE tenant_id = $1 AND id = $2)",
            tenant_id,
            webhook_id,
        )
        if not webhook_exists:
            raise HTTPException(status_code=404, detail="Webhook not found")
        rows = await conn.fetch(
            """
            SELECT id, event_name, status, attempts, next_attempt_at,
                   last_status_code, last_error, created_at, delivered_at
            FROM webhook_deliveries
            WHERE tenant_id = $1 AND webhook_id = $2
            ORDER BY created_at DESC, id DESC
            LIMIT $3
            """,
            tenant_id,
            webhook_id,
            limit,
        )
    return {"items": [dict(row) for row in rows]}


@router.patch(
    "/admin/tenants/{tenant_id}/webhooks/{webhook_id}",
    dependencies=[Depends(require_owner), Depends(rate_limited(budget="webhook-write"))],
)
async def update_webhook(
    tenant_id: str,
    webhook_id: int,
    request: WebhookUpdateRequest,
    principal: AuthPrincipal = Depends(require_owner),
):
    updates = request.model_dump(exclude_unset=True)
    if not updates:
        raise HTTPException(status_code=400, detail="At least one webhook field is required")
    if any(field in updates and updates[field] is None for field in ("target_url", "events", "is_enabled")):
        raise HTTPException(status_code=422, detail="Webhook fields cannot be cleared")
    columns = list(updates)
    assignments = ", ".join(f"{column} = ${index + 3}" for index, column in enumerate(columns))
    values = [tenant_id, webhook_id, *(updates[column] for column in columns)]
    async with tenant_connection(tenant_id) as conn:
        row = await conn.fetchrow(
            f"""
            UPDATE tenant_webhooks
            SET {assignments}, updated_at = now()
            WHERE tenant_id = $1 AND id = $2
            RETURNING id, target_url, events, is_enabled
            """,
            *values,
        )
        if row is None:
            raise HTTPException(status_code=404, detail="Webhook not found")
        if updates.get("is_enabled") is False:
            await conn.execute(
                """
                UPDATE webhook_deliveries
                SET status = 'failed', last_error = 'Webhook disabled', lease_expires_at = NULL
                WHERE tenant_id = $1 AND webhook_id = $2 AND status = 'pending'
                """,
                tenant_id,
                webhook_id,
            )
        await write_audit(
            conn, tenant_id, "webhook.updated", principal.user_id,
            "tenant_webhook", webhook_id, {"fields": columns},
        )
    return dict(row)


@router.delete(
    "/admin/tenants/{tenant_id}/webhooks/{webhook_id}",
    dependencies=[Depends(require_owner), Depends(rate_limited(budget="webhook-write"))],
)
async def disable_webhook(
    tenant_id: str,
    webhook_id: int,
    principal: AuthPrincipal = Depends(require_owner),
):
    async with tenant_connection(tenant_id) as conn:
        updated = await conn.fetchval(
            """
            UPDATE tenant_webhooks SET is_enabled = FALSE, updated_at = now()
            WHERE tenant_id = $1 AND id = $2 RETURNING id
            """,
            tenant_id,
            webhook_id,
        )
        if updated is None:
            raise HTTPException(status_code=404, detail="Webhook not found")
        await conn.execute(
            """
            UPDATE webhook_deliveries
            SET status = 'failed', last_error = 'Webhook disabled', lease_expires_at = NULL
            WHERE tenant_id = $1 AND webhook_id = $2 AND status = 'pending'
            """,
            tenant_id,
            webhook_id,
        )
        await write_audit(
            conn, tenant_id, "webhook.disabled", principal.user_id,
            "tenant_webhook", webhook_id,
        )
    return {"id": updated, "disabled": True}


@router.post(
    "/admin/tenants/{tenant_id}/webhooks/{webhook_id}/rotate-secret",
    dependencies=[Depends(require_owner), Depends(rate_limited(budget="webhook-write"))],
)
async def rotate_webhook_secret(
    tenant_id: str,
    webhook_id: int,
    principal: AuthPrincipal = Depends(require_owner),
):
    signing_secret = secrets.token_urlsafe(32)
    async with tenant_connection(tenant_id) as conn:
        updated = await conn.fetchval(
            """
            UPDATE tenant_webhooks
            SET encrypted_signing_secret = $3, updated_at = now()
            WHERE tenant_id = $1 AND id = $2
            RETURNING id
            """,
            tenant_id,
            webhook_id,
            encrypt(signing_secret),
        )
        if updated is None:
            raise HTTPException(status_code=404, detail="Webhook not found")
        await write_audit(
            conn, tenant_id, "webhook.secret_rotated", principal.user_id,
            "tenant_webhook", webhook_id,
        )
    return {"id": updated, "signing_secret": signing_secret}
