"""Tenant subscriptions and Razorpay test-mode billing integration."""

from __future__ import annotations

import hashlib
import hmac
import json
import os
import re
from datetime import datetime, timezone
from typing import Protocol

import httpx
from fastapi import APIRouter, Depends, Header, HTTPException, Request
from pydantic import BaseModel, Field

from audit import write_audit
from auth import AuthPrincipal, require_owner
from db import tenant_connection
from rate_limit import rate_limited

router = APIRouter()
_TENANT_SLUG_RE = re.compile(r"^[a-z0-9][a-z0-9-]{0,62}$")
_MAX_WEBHOOK_BYTES = 1_048_576
_WARNING_THRESHOLD = 0.8
_OPEN_SUBSCRIPTION_STATUSES = (
    "created",
    "authenticated",
    "active",
    "pending",
    "halted",
    "paused",
)
_SUBSCRIPTION_STATUSES = set(_OPEN_SUBSCRIPTION_STATUSES) | {
    "cancelled",
    "completed",
    "expired",
    "failed",
}
_EVENT_STATUS = {
    "subscription.authenticated": "authenticated",
    "subscription.activated": "active",
    "subscription.charged": "active",
    "subscription.pending": "pending",
    "subscription.halted": "halted",
    "subscription.paused": "paused",
    "subscription.resumed": "active",
    "subscription.cancelled": "cancelled",
    "subscription.completed": "completed",
}


class SubscriptionRequest(BaseModel):
    plan_slug: str = Field(pattern=r"^[a-z0-9][a-z0-9-]{0,62}$")


class BillingProvider(Protocol):
    async def create_subscription(
        self, provider_plan_id: str, tenant_id: str, plan_slug: str
    ) -> dict[str, str]: ...


class BillingProviderError(Exception):
    """A provider request could not be completed safely."""


def _test_mode_provider_config() -> tuple[str, str]:
    key_id = os.environ.get("RAZORPAY_KEY_ID", "")
    key_secret = os.environ.get("RAZORPAY_KEY_SECRET", "")
    if not key_id or not key_secret:
        raise HTTPException(status_code=503, detail="Razorpay test-mode billing is not configured")
    if not key_id.startswith("rzp_test_"):
        raise HTTPException(status_code=503, detail="Only Razorpay test-mode credentials are accepted")
    return key_id, key_secret


def billing_provider_configured() -> bool:
    key_id = os.environ.get("RAZORPAY_KEY_ID", "")
    return bool(key_id.startswith("rzp_test_") and os.environ.get("RAZORPAY_KEY_SECRET"))


class RazorpayTestProvider:
    def __init__(self, key_id: str, key_secret: str):
        if not key_id.startswith("rzp_test_"):
            raise ValueError("Razorpay live credentials are not accepted")
        self._key_id = key_id
        self._key_secret = key_secret

    async def create_subscription(
        self, provider_plan_id: str, tenant_id: str, plan_slug: str
    ) -> dict[str, str]:
        try:
            total_count = int(os.environ.get("RAZORPAY_SUBSCRIPTION_TOTAL_COUNT", "120"))
        except ValueError as exc:
            raise BillingProviderError("Razorpay subscription cycle configuration is invalid") from exc
        if total_count < 1:
            raise BillingProviderError("Razorpay subscription cycle count must be positive")

        payload = {
            "plan_id": provider_plan_id,
            "total_count": total_count,
            "quantity": 1,
            "customer_notify": True,
            "notes": {"tenant_id": tenant_id, "plan_slug": plan_slug},
        }
        try:
            async with httpx.AsyncClient(
                timeout=10.0,
                auth=(self._key_id, self._key_secret),
            ) as client:
                response = await client.post(
                    "https://api.razorpay.com/v1/subscriptions",
                    json=payload,
                )
                response.raise_for_status()
                result = response.json()
        except (httpx.HTTPError, ValueError) as exc:
            raise BillingProviderError("Razorpay could not create the subscription") from exc

        subscription_id = result.get("id") if isinstance(result, dict) else None
        checkout_url = result.get("short_url") if isinstance(result, dict) else None
        status = result.get("status", "created") if isinstance(result, dict) else None
        if (
            not isinstance(subscription_id, str)
            or not subscription_id
            or not isinstance(checkout_url, str)
            or not checkout_url
            or not isinstance(status, str)
            or status not in _SUBSCRIPTION_STATUSES
        ):
            raise BillingProviderError("Razorpay returned an incomplete subscription response")
        return {
            "subscription_id": subscription_id,
            "checkout_url": checkout_url,
            "status": status,
        }


def create_billing_provider() -> BillingProvider:
    key_id, key_secret = _test_mode_provider_config()
    return RazorpayTestProvider(key_id, key_secret)


def verify_webhook_signature(raw_body: bytes, signature: str, secret: str) -> bool:
    expected = hmac.new(secret.encode("utf-8"), raw_body, hashlib.sha256).hexdigest()
    return hmac.compare_digest(expected, signature)


def build_usage_warnings(
    plan: dict | None,
    usage: dict[str, int],
) -> list[dict[str, int | str]]:
    if plan is None:
        return []

    warnings = []
    for event_type, limit_field in (
        ("call", "calls_limit"),
        ("sms", "sms_limit"),
        ("whatsapp", "whatsapp_limit"),
    ):
        limit = plan.get(limit_field)
        if limit is None:
            continue
        units = usage.get(event_type, 0)
        if limit == 0:
            ratio = 1.0 if units else 0.0
        else:
            ratio = units / limit
        if ratio >= _WARNING_THRESHOLD:
            warnings.append(
                {
                    "event_type": event_type,
                    "used": units,
                    "limit": limit,
                    "level": "limit_reached" if units >= limit else "approaching_limit",
                }
            )
    return warnings


def _unix_timestamp(value: object) -> datetime | None:
    if not isinstance(value, int) or value <= 0:
        return None
    return datetime.fromtimestamp(value, tz=timezone.utc)


@router.get(
    "/admin/tenants/{tenant_id}/billing",
    dependencies=[Depends(require_owner), Depends(rate_limited(budget="billing-read"))],
)
async def get_billing_summary(tenant_id: str):
    async with tenant_connection(tenant_id) as conn:
        plans = await conn.fetch(
            """
            SELECT slug, display_name, description, price_minor, currency,
                   calls_limit, sms_limit, whatsapp_limit,
                   (razorpay_plan_id IS NOT NULL) AS provider_plan_configured
            FROM billing_plans
            WHERE is_active
            ORDER BY price_minor NULLS FIRST, slug
            """
        )
        subscription = await conn.fetchrow(
            """
            SELECT subscription.id, subscription.plan_slug, subscription.plan_name,
                   subscription.status, subscription.checkout_url,
                   subscription.current_period_start, subscription.current_period_end,
                   subscription.created_at, subscription.updated_at,
                   plan.calls_limit, plan.sms_limit, plan.whatsapp_limit
            FROM billing_subscriptions AS subscription
            LEFT JOIN billing_plans AS plan ON plan.slug = subscription.plan_slug
            WHERE subscription.tenant_id = $1
            ORDER BY subscription.created_at DESC, subscription.id DESC
            LIMIT 1
            """,
            tenant_id,
        )
        usage_rows = await conn.fetch(
            """
            SELECT event_type, event_count, units
            FROM monthly_usage
            WHERE tenant_id = $1 AND month = date_trunc('month', now())
            """,
            tenant_id,
        )

    current_plan = next(
        (dict(plan) for plan in plans if subscription and plan["slug"] == subscription["plan_slug"]),
        dict(subscription) if subscription else None,
    )
    usage_items = [dict(row) for row in usage_rows]
    usage_by_type = {row["event_type"]: int(row["units"]) for row in usage_items}
    return {
        "provider": "razorpay",
        "provider_configured": billing_provider_configured(),
        "plans": [dict(plan) for plan in plans],
        "subscription": dict(subscription) if subscription else None,
        "usage": {
            "month": datetime.now(timezone.utc).strftime("%Y-%m"),
            "items": usage_items,
        },
        "warnings": build_usage_warnings(current_plan, usage_by_type),
        "limits_are_advisory": True,
    }


@router.post(
    "/admin/tenants/{tenant_id}/billing/subscription",
    dependencies=[Depends(require_owner), Depends(rate_limited(budget="billing-write"))],
)
async def create_subscription(
    tenant_id: str,
    request: SubscriptionRequest,
    principal: AuthPrincipal = Depends(require_owner),
):
    async with tenant_connection(tenant_id) as conn:
        await conn.execute(
            "SELECT pg_advisory_xact_lock(hashtextextended($1, 0))",
            f"billing-subscription:{tenant_id}",
        )
        existing = await conn.fetchrow(
            """
            SELECT status
            FROM billing_subscriptions
            WHERE tenant_id = $1 AND status = ANY($2::text[])
            LIMIT 1
            """,
            tenant_id,
            list(_OPEN_SUBSCRIPTION_STATUSES),
        )
        if existing:
            raise HTTPException(
                status_code=409,
                detail=f"Tenant already has a {existing['status']} subscription",
            )

        plan = await conn.fetchrow(
            """
            SELECT slug, display_name, price_minor, currency, razorpay_plan_id
            FROM billing_plans
            WHERE slug = $1 AND is_active
            """,
            request.plan_slug,
        )
        if plan is None:
            raise HTTPException(status_code=404, detail="Active billing plan not found")
        if plan["price_minor"] is None or plan["razorpay_plan_id"] is None:
            raise HTTPException(
                status_code=503,
                detail="Plan pricing and a Razorpay test-mode plan must be configured first",
            )
        if not plan["razorpay_plan_id"].strip():
            raise HTTPException(
                status_code=503,
                detail="Plan pricing and a Razorpay test-mode plan must be configured first",
            )

        try:
            provider = create_billing_provider()
            remote = await provider.create_subscription(
                plan["razorpay_plan_id"], tenant_id, plan["slug"]
            )
        except BillingProviderError as exc:
            raise HTTPException(status_code=503, detail=str(exc)) from exc

        await conn.execute(
            """
            INSERT INTO billing_subscriptions
                (tenant_id, plan_slug, plan_name, provider,
                 provider_subscription_id, status, checkout_url)
            VALUES ($1, $2, $3, 'razorpay', $4, $5, $6)
            """,
            tenant_id,
            plan["slug"],
            plan["display_name"],
            remote["subscription_id"],
            remote["status"],
            remote["checkout_url"],
        )
        await write_audit(
            conn,
            tenant_id,
            "billing.subscription_created",
            principal.user_id,
            "billing_subscription",
            remote["subscription_id"],
            {"plan_slug": plan["slug"], "provider": "razorpay"},
        )

    return {
        "provider": "razorpay",
        "subscription_id": remote["subscription_id"],
        "status": remote["status"],
        "checkout_url": remote["checkout_url"],
    }


async def _read_limited_body(request: Request) -> bytes:
    content_length = request.headers.get("content-length")
    if content_length:
        try:
            if int(content_length) > _MAX_WEBHOOK_BYTES:
                raise HTTPException(status_code=413, detail="Webhook payload is too large")
        except ValueError as exc:
            raise HTTPException(status_code=400, detail="Invalid Content-Length") from exc

    chunks = []
    total = 0
    async for chunk in request.stream():
        total += len(chunk)
        if total > _MAX_WEBHOOK_BYTES:
            raise HTTPException(status_code=413, detail="Webhook payload is too large")
        chunks.append(chunk)
    return b"".join(chunks)


@router.post("/webhooks/razorpay")
async def receive_razorpay_webhook(
    request: Request,
    signature: str | None = Header(default=None, alias="X-Razorpay-Signature"),
    provider_event_id: str | None = Header(default=None, alias="X-Razorpay-Event-Id"),
):
    if not billing_provider_configured():
        raise HTTPException(status_code=503, detail="Razorpay test-mode billing is not configured")
    secret = os.environ.get("RAZORPAY_WEBHOOK_SECRET")
    if not secret:
        raise HTTPException(status_code=503, detail="Razorpay webhook verification is not configured")
    raw_body = await _read_limited_body(request)
    if not signature or not verify_webhook_signature(raw_body, signature, secret):
        raise HTTPException(status_code=401, detail="Invalid Razorpay webhook signature")

    try:
        event = json.loads(raw_body)
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise HTTPException(status_code=400, detail="Invalid JSON webhook payload") from exc

    event_name = event.get("event") if isinstance(event, dict) else None
    if not isinstance(event_name, str):
        raise HTTPException(status_code=400, detail="Webhook event name is invalid")
    resulting_status = _EVENT_STATUS.get(event_name)
    if resulting_status is None:
        return {"status": "ignored"}

    try:
        entity = event["payload"]["subscription"]["entity"]
        subscription_id = entity["id"]
        tenant_id = entity["notes"]["tenant_id"]
    except (KeyError, TypeError) as exc:
        raise HTTPException(status_code=400, detail="Webhook is missing subscription metadata") from exc
    if (
        not isinstance(subscription_id, str)
        or not isinstance(tenant_id, str)
        or not _TENANT_SLUG_RE.fullmatch(tenant_id)
    ):
        raise HTTPException(status_code=400, detail="Webhook subscription metadata is invalid")

    event_id = provider_event_id or hashlib.sha256(raw_body).hexdigest()
    if len(event_id) > 255:
        raise HTTPException(status_code=400, detail="Webhook event identifier is invalid")

    async with tenant_connection(tenant_id) as conn:
        inserted = await conn.fetchval(
            """
            INSERT INTO billing_webhook_events
                (tenant_id, provider_event_id, event_name, provider_subscription_id)
            VALUES ($1, $2, $3, $4)
            ON CONFLICT (tenant_id, provider_event_id) DO NOTHING
            RETURNING id
            """,
            tenant_id,
            event_id,
            event_name,
            subscription_id,
        )
        if inserted is None:
            return {"status": "duplicate"}

        updated = await conn.fetchval(
            """
            UPDATE billing_subscriptions
            SET status = $3,
                current_period_start = COALESCE($4, current_period_start),
                current_period_end = COALESCE($5, current_period_end),
                updated_at = now()
            WHERE tenant_id = $1 AND provider = 'razorpay'
              AND provider_subscription_id = $2
            RETURNING id
            """,
            tenant_id,
            subscription_id,
            resulting_status,
            _unix_timestamp(entity.get("current_start")),
            _unix_timestamp(entity.get("current_end")),
        )
        if updated is None:
            raise HTTPException(status_code=404, detail="Subscription is not registered")
        await conn.execute(
            "UPDATE billing_webhook_events SET processed_at = now() WHERE tenant_id = $1 AND id = $2",
            tenant_id,
            inserted,
        )

    return {"status": "processed"}
