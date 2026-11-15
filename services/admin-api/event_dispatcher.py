"""One-shot delivery worker for tenant webhook and email outboxes.

Run periodically with a scheduler. Delivery is at-least-once: a process
crash after a remote server accepts a webhook but before the DB update can
cause that delivery to be retried.
"""

from __future__ import annotations

import argparse
import asyncio
import hashlib
import hmac
import json
from datetime import datetime, timedelta, timezone

import httpx
from cryptography.fernet import InvalidToken

from crypto import decrypt
from db import get_pool, tenant_connection
from email_provider import EmailDeliveryError, send_email
from webhooks import validate_webhook_url

MAX_ATTEMPTS = 8
LEASE_SECONDS = 120


async def _active_tenants() -> list[str]:
    pool = await get_pool()
    async with pool.acquire() as conn:
        rows = await conn.fetch("SELECT public.platform_list_active_tenants() AS tenant_id")
    return [row["tenant_id"] for row in rows]


async def _claim_webhook(tenant_id: str):
    async with tenant_connection(tenant_id) as conn:
        return await conn.fetchrow(
            """
            WITH next_delivery AS (
                SELECT delivery.id
                FROM webhook_deliveries AS delivery
                JOIN tenant_webhooks AS hook
                  ON hook.id = delivery.webhook_id
                 AND hook.tenant_id = delivery.tenant_id
                WHERE delivery.tenant_id = $1 AND delivery.status = 'pending'
                  AND delivery.attempts < $2
                  AND delivery.next_attempt_at <= now()
                  AND (delivery.lease_expires_at IS NULL OR delivery.lease_expires_at < now())
                  AND hook.is_enabled
                ORDER BY delivery.next_attempt_at, delivery.id
                FOR UPDATE OF delivery SKIP LOCKED
                LIMIT 1
            )
            UPDATE webhook_deliveries AS delivery
            SET lease_expires_at = now() + ($3 * interval '1 second')
            FROM next_delivery, tenant_webhooks AS hook
            WHERE delivery.id = next_delivery.id
              AND hook.id = delivery.webhook_id
              AND hook.tenant_id = delivery.tenant_id
            RETURNING delivery.id, delivery.webhook_id, delivery.event_name,
                      delivery.payload, delivery.attempts,
                      hook.target_url, hook.encrypted_signing_secret
            """,
            tenant_id,
            MAX_ATTEMPTS,
            LEASE_SECONDS,
        )


async def _finish_webhook(
    tenant_id: str,
    delivery_id: int,
    attempt: int,
    delivered: bool,
    status_code: int | None,
    error: str | None,
) -> None:
    terminal = delivered or attempt >= MAX_ATTEMPTS
    status = "delivered" if delivered else "failed" if terminal else "pending"
    retry_at = datetime.now(timezone.utc) + timedelta(
        seconds=min(30 * (2 ** max(attempt - 1, 0)), 3600)
    )
    async with tenant_connection(tenant_id) as conn:
        await conn.execute(
            """
            UPDATE webhook_deliveries
            SET attempts = $3, status = $4, next_attempt_at = $5,
                lease_expires_at = NULL, last_status_code = $6,
                last_error = $7, delivered_at = CASE WHEN $4 = 'delivered' THEN now() ELSE NULL END
            WHERE tenant_id = $1 AND id = $2
            """,
            tenant_id,
            delivery_id,
            attempt,
            status,
            retry_at,
            status_code,
            error[:500] if error else None,
        )


async def _deliver_webhook(client: httpx.AsyncClient, tenant_id: str, delivery) -> None:
    attempt = delivery["attempts"] + 1
    try:
        validate_webhook_url(delivery["target_url"])
        payload = delivery["payload"]
        body = payload.encode() if isinstance(payload, str) else json.dumps(
            payload, separators=(",", ":"), ensure_ascii=False
        ).encode()
        secret = decrypt(delivery["encrypted_signing_secret"])
        signature = hmac.new(secret.encode(), body, hashlib.sha256).hexdigest()
        response = await client.post(
            delivery["target_url"],
            content=body,
            headers={
                "Content-Type": "application/json",
                "X-Propview-Event": delivery["event_name"],
                "X-Propview-Delivery": str(delivery["id"]),
                "X-Propview-Signature": f"sha256={signature}",
            },
        )
        ok = 200 <= response.status_code < 300
        await _finish_webhook(
            tenant_id,
            delivery["id"],
            attempt,
            ok,
            response.status_code,
            None if ok else f"Webhook returned HTTP {response.status_code}",
        )
    except InvalidToken:
        await _finish_webhook(
            tenant_id,
            delivery["id"],
            MAX_ATTEMPTS,
            False,
            None,
            "Webhook signing secret could not be decrypted",
        )
    except (httpx.RequestError, ValueError) as exc:
        await _finish_webhook(
            tenant_id,
            delivery["id"],
            attempt,
            False,
            None,
            f"Webhook request failed: {type(exc).__name__}",
        )


async def _claim_email(tenant_id: str):
    async with tenant_connection(tenant_id) as conn:
        return await conn.fetchrow(
            """
            WITH next_email AS (
                SELECT id FROM email_outbox
                WHERE tenant_id = $1 AND status = 'pending' AND attempts < $2
                  AND next_attempt_at <= now()
                  AND (lease_expires_at IS NULL OR lease_expires_at < now())
                ORDER BY next_attempt_at, id
                FOR UPDATE SKIP LOCKED
                LIMIT 1
            )
            UPDATE email_outbox AS item
            SET lease_expires_at = now() + ($3 * interval '1 second')
            FROM next_email
            WHERE item.id = next_email.id
            RETURNING item.id, item.recipient, item.subject, item.body, item.attempts
            """,
            tenant_id,
            MAX_ATTEMPTS,
            LEASE_SECONDS,
        )


async def _finish_email(
    tenant_id: str, item_id: int, attempt: int, sent: bool, error: str | None
) -> None:
    terminal = sent or attempt >= MAX_ATTEMPTS
    status = "sent" if sent else "failed" if terminal else "pending"
    retry_at = datetime.now(timezone.utc) + timedelta(
        seconds=min(30 * (2 ** max(attempt - 1, 0)), 3600)
    )
    async with tenant_connection(tenant_id) as conn:
        await conn.execute(
            """
            UPDATE email_outbox
            SET attempts = $3, status = $4, next_attempt_at = $5,
                lease_expires_at = NULL, last_error = $6,
                sent_at = CASE WHEN $4 = 'sent' THEN now() ELSE NULL END
            WHERE tenant_id = $1 AND id = $2
            """,
            tenant_id,
            item_id,
            attempt,
            status,
            retry_at,
            error[:500] if error else None,
        )


async def _deliver_email(tenant_id: str, item) -> None:
    attempt = item["attempts"] + 1
    try:
        await send_email(item["recipient"], item["subject"], item["body"])
        await _finish_email(tenant_id, item["id"], attempt, True, None)
    except EmailDeliveryError as exc:
        await _finish_email(
            tenant_id,
            item["id"],
            attempt,
            False,
            f"Email request failed: {type(exc).__name__}",
        )


async def dispatch_tenant(
    tenant_id: str,
    client: httpx.AsyncClient,
    limit: int = 100,
) -> dict[str, int]:
    webhook_attempts = 0
    email_attempts = 0
    for _ in range(limit):
        delivery = await _claim_webhook(tenant_id)
        if delivery is None:
            break
        await _deliver_webhook(client, tenant_id, delivery)
        webhook_attempts += 1
    for _ in range(limit):
        item = await _claim_email(tenant_id)
        if item is None:
            break
        await _deliver_email(tenant_id, item)
        email_attempts += 1
    return {"webhook_attempts": webhook_attempts, "email_attempts": email_attempts}


async def run_dispatch(limit: int = 100) -> dict[str, int]:
    delivered_webhooks = 0
    sent_emails = 0
    async with httpx.AsyncClient(timeout=10.0, follow_redirects=False) as client:
        for tenant_id in await _active_tenants():
            result = await dispatch_tenant(tenant_id, client, limit)
            delivered_webhooks += result["webhook_attempts"]
            sent_emails += result["email_attempts"]
    return {"webhook_attempts": delivered_webhooks, "email_attempts": sent_emails}


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--limit", type=int, default=100, help="Maximum attempts per tenant and channel")
    args = parser.parse_args()
    if args.limit < 1:
        parser.error("--limit must be positive")
    print(asyncio.run(run_dispatch(args.limit)))


if __name__ == "__main__":
    main()
