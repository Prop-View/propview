"""Phase 3 account and product API integration tests.

Postgres and Redis are real local services. Only SMTP and Google OAuth's
remote token endpoint are replaced at their outbound API boundaries.
"""

from __future__ import annotations

import os
import re
import sys
import uuid
from datetime import datetime, timedelta, timezone
from pathlib import Path
from urllib.parse import parse_qs, urlsplit

import pytest
from fastapi.testclient import TestClient

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
os.environ.setdefault("DATABASE_URL", "postgresql://localhost/propview_dev")
os.environ.setdefault("PLATFORM_OPERATOR_TOKEN", "test-platform-token")
os.environ.setdefault("RATE_LIMIT_AUTH_REQUESTS_PER_WINDOW", "10000")
os.environ.setdefault("RATE_LIMIT_ADMIN_REQUESTS_PER_WINDOW", "10000")
os.environ.setdefault("RATE_LIMIT_DASHBOARD_REQUESTS_PER_WINDOW", "10000")

import accounts
import calendar_oauth
import event_dispatcher
import webhooks
from db import tenant_connection
from main import app


def _tenant_id() -> str:
    return f"test-phase3-{uuid.uuid4().hex[:20]}"


async def _cleanup_tenant(tenant_id: str) -> None:
    async with tenant_connection(tenant_id) as conn:
        await conn.execute("DELETE FROM audit_log WHERE tenant_id = $1", tenant_id)
        await conn.execute("DELETE FROM email_outbox WHERE tenant_id = $1", tenant_id)
        await conn.execute("DELETE FROM tenant_webhooks WHERE tenant_id = $1", tenant_id)
        await conn.execute("DELETE FROM account_users WHERE tenant_id = $1", tenant_id)
        await conn.execute("DELETE FROM tenant_settings WHERE tenant_id = $1", tenant_id)
        await conn.execute("DELETE FROM interactions WHERE tenant_id = $1", tenant_id)
        await conn.execute("DELETE FROM appointments WHERE tenant_id = $1", tenant_id)
        await conn.execute("DELETE FROM leads WHERE tenant_id = $1", tenant_id)
        await conn.execute("DELETE FROM contacts WHERE tenant_id = $1", tenant_id)
        await conn.execute("DELETE FROM properties WHERE tenant_id = $1", tenant_id)
        await conn.execute("DELETE FROM projects WHERE tenant_id = $1", tenant_id)


@pytest.fixture
def api():
    tenants: list[str] = []
    with TestClient(app) as client:
        yield client, tenants
        for tenant_id in tenants:
            client.portal.call(_cleanup_tenant, tenant_id)


def _fake_email(monkeypatch, sent: list[dict[str, str]]) -> None:
    async def send(recipient: str, subject: str, body: str) -> None:
        sent.append({"recipient": recipient, "subject": subject, "body": body})

    monkeypatch.setattr(accounts, "send_email", send)


def _token_from_email(message: dict[str, str]) -> str:
    match = re.search(r"https?://\S+", message["body"])
    assert match is not None
    return parse_qs(urlsplit(match.group(0)).query)["token"][0]


def _signup_and_login(client: TestClient, tenants: list[str], monkeypatch) -> tuple[str, str, list]:
    tenant_id = _tenant_id()
    tenants.append(tenant_id)
    sent: list[dict[str, str]] = []
    _fake_email(monkeypatch, sent)
    signup = client.post(
        "/auth/signup",
        json={
            "tenant_slug": tenant_id,
            "tenant_name": "Test Agency",
            "owner_name": "Test Owner",
            "email": f"owner-{tenant_id}@example.com",
            "password": "a-secure-test-password",
        },
    )
    assert signup.status_code == 200, signup.text
    verification = client.post(
        f"/auth/{tenant_id}/verify-email",
        json={"token": _token_from_email(sent[-1])},
    )
    assert verification.status_code == 200, verification.text
    login = client.post(
        "/auth/login",
        json={
            "tenant_slug": tenant_id,
            "email": f"owner-{tenant_id}@example.com",
            "password": "a-secure-test-password",
        },
    )
    assert login.status_code == 200, login.text
    return tenant_id, login.json()["access_token"], sent


def test_health_checks_postgres_and_redis(api):
    client, _ = api

    response = client.get("/health")

    assert response.status_code == 200
    assert response.json() == {
        "status": "ok",
        "service": "admin-api",
        "dependencies": {"postgres": "connected", "redis": "connected"},
    }


def test_signup_verification_session_and_password_reset(api, monkeypatch):
    client, tenants = api
    tenant_id = _tenant_id()
    tenants.append(tenant_id)
    email = f"owner-{tenant_id}@example.com"
    sent: list[dict[str, str]] = []
    _fake_email(monkeypatch, sent)

    response = client.post(
        "/auth/signup",
        json={
            "tenant_slug": tenant_id,
            "tenant_name": "Test Agency",
            "owner_name": "Test Owner",
            "email": email,
            "password": "a-secure-test-password",
        },
    )
    assert response.status_code == 200
    assert response.json() == {"tenant_slug": tenant_id, "status": "verification_required"}
    assert "access_token" not in response.json()

    before_verify = client.post(
        "/auth/login",
        json={"tenant_slug": tenant_id, "email": email, "password": "a-secure-test-password"},
    )
    assert before_verify.status_code == 403

    verification_token = _token_from_email(sent[-1])
    assert client.post(
        f"/auth/{tenant_id}/verify-email", json={"token": verification_token}
    ).status_code == 200
    assert client.post(
        f"/auth/{tenant_id}/verify-email", json={"token": verification_token}
    ).status_code == 400

    login = client.post(
        "/auth/login",
        json={"tenant_slug": tenant_id, "email": email, "password": "a-secure-test-password"},
    )
    assert login.status_code == 200
    old_session = login.json()["access_token"]
    client.headers["Authorization"] = f"Bearer {old_session}"
    assert client.get(f"/auth/{tenant_id}/me").json()["role"] == "owner"
    assert client.get(f"/auth/{_tenant_id()}/me").status_code == 401

    async def token_is_hashed() -> bool:
        async with tenant_connection(tenant_id) as conn:
            stored = await conn.fetchval(
                "SELECT token_hash FROM account_tokens WHERE tenant_id = $1 AND purpose = 'email_verification'",
                tenant_id,
            )
        return stored != verification_token

    assert client.portal.call(token_is_hashed)

    reset_request = client.post(
        "/auth/password-reset/request",
        json={"tenant_slug": tenant_id, "email": email},
    )
    assert reset_request.status_code == 200
    reset_token = _token_from_email(sent[-1])
    reset = client.post(
        "/auth/password-reset/confirm",
        json={
            "tenant_slug": tenant_id,
            "token": reset_token,
            "password": "a-different-secure-password",
        },
    )
    assert reset.status_code == 200
    assert client.get(f"/auth/{tenant_id}/me").status_code == 401
    assert client.post(
        "/auth/login",
        json={"tenant_slug": tenant_id, "email": email, "password": "a-secure-test-password"},
    ).status_code == 401
    assert client.post(
        "/auth/login",
        json={"tenant_slug": tenant_id, "email": email, "password": "a-different-secure-password"},
    ).status_code == 200


def test_session_team_invitation_and_owner_permissions(api, monkeypatch):
    client, tenants = api
    tenant_id, owner_token, sent = _signup_and_login(client, tenants, monkeypatch)
    client.headers["Authorization"] = f"Bearer {owner_token}"

    invitation = client.post(
        f"/admin/tenants/{tenant_id}/team/invitations",
        json={"email": f"agent-{tenant_id}@example.com", "display_name": "Test Agent"},
    )
    assert invitation.status_code == 200, invitation.text
    assert client.get(f"/admin/tenants/{tenant_id}/team").json()["items"][0]["role"] == "owner"
    invite_token = _token_from_email(sent[-1])
    accepted = client.post(
        f"/auth/{tenant_id}/team/accept",
        json={"token": invite_token, "password": "agent-secure-password"},
    )
    assert accepted.status_code == 200

    agent_login = client.post(
        "/auth/login",
        json={
            "tenant_slug": tenant_id,
            "email": f"agent-{tenant_id}@example.com",
            "password": "agent-secure-password",
        },
    )
    assert agent_login.status_code == 200
    client.headers["Authorization"] = f"Bearer {agent_login.json()['access_token']}"
    assert client.get(f"/admin/tenants/{tenant_id}/team").status_code == 403
    assert client.put(
        f"/admin/tenants/{tenant_id}/settings", json={}
    ).status_code == 403

    client.headers["Authorization"] = f"Bearer {owner_token}"
    assert client.delete(
        f"/admin/tenants/{tenant_id}/team/{invitation.json()['user_id']}"
    ).json()["status"] == "deactivated"
    assert client.post(
        f"/auth/{tenant_id}/team/accept",
        json={"token": invite_token, "password": "agent-secure-password"},
    ).status_code == 400


def test_listing_csv_lead_and_appointment_writes_are_tenant_scoped(api, monkeypatch):
    client, tenants = api
    tenant_id, owner_token, _ = _signup_and_login(client, tenants, monkeypatch)
    client.headers["Authorization"] = f"Bearer {owner_token}"

    upload = client.post(
        f"/admin/tenants/{tenant_id}/listings/upload-csv",
        files={
            "file": (
                "inventory.csv",
                "address,city,state,property_type,price,amenities\n"
                "1 Test St,Austin,TX,house,450000,pool|garage\n",
                "text/csv",
            )
        },
    )
    assert upload.status_code == 200, upload.text
    property_id = upload.json()["ids"][0]

    async def seed_crm() -> tuple[int, int]:
        async with tenant_connection(tenant_id) as conn:
            contact_id = await conn.fetchval(
                """
                INSERT INTO contacts (tenant_id, full_name, phone_number, email)
                VALUES ($1, 'Test Caller', $2, 'caller@example.com') RETURNING id
                """,
                tenant_id,
                f"+1555{uuid.uuid4().int % 10**7:07d}",
            )
            lead_id = await conn.fetchval(
                """
                INSERT INTO leads (tenant_id, contact_id, property_id, priority, status)
                VALUES ($1, $2, $3, 'medium', 'new') RETURNING id
                """,
                tenant_id,
                contact_id,
                property_id,
            )
            appointment_id = await conn.fetchval(
                """
                INSERT INTO appointments (tenant_id, lead_id, property_id, scheduled_at)
                VALUES ($1, $2, $3, now() + interval '2 days') RETURNING id
                """,
                tenant_id,
                lead_id,
                property_id,
            )
        return lead_id, appointment_id

    lead_id, appointment_id = client.portal.call(seed_crm)
    lead_update = client.patch(
        f"/admin/tenants/{tenant_id}/leads/{lead_id}",
        json={"status": "qualified", "notes": "Requested a showing"},
    )
    assert lead_update.status_code == 200, lead_update.text
    assert lead_update.json()["notes"] == "Requested a showing"

    new_time = (datetime.now(timezone.utc) + timedelta(days=4)).isoformat()
    reschedule = client.patch(
        f"/admin/tenants/{tenant_id}/appointments/{appointment_id}",
        json={"scheduled_at": new_time},
    )
    assert reschedule.status_code == 200
    assert reschedule.json()["scheduled_at"].startswith(new_time[:19])
    assert client.patch(
        f"/admin/tenants/{tenant_id}/appointments/{appointment_id}",
        json={"status": "cancelled"},
    ).json()["status"] == "cancelled"

    listing_update = client.patch(
        f"/admin/tenants/{tenant_id}/properties/{property_id}",
        json={"price": 475000, "status": "pending"},
    )
    assert listing_update.status_code == 200, listing_update.text
    assert listing_update.json()["price"] == 475000.0
    assert client.delete(
        f"/admin/tenants/{tenant_id}/properties/{property_id}"
    ).json()["deleted"] is True
    assert client.patch(
        f"/admin/tenants/{_tenant_id()}/leads/{lead_id}",
        json={"notes": "Cross-tenant attempt"},
    ).status_code == 401

    monkeypatch.delenv("GEMINI_API_KEY", raising=False)
    unsupported = client.post(
        f"/admin/tenants/{tenant_id}/knowledge-base/documents",
        data={"source_type": "faq"},
        files={"file": ("unsupported.docx", b"text", "application/octet-stream")},
    )
    assert unsupported.status_code == 415
    no_provider_key = client.post(
        f"/admin/tenants/{tenant_id}/knowledge-base/documents",
        data={"source_type": "faq"},
        files={"file": ("faq.txt", b"Frequently asked questions", "text/plain")},
    )
    assert no_provider_key.status_code == 503


def test_google_oauth_connect_state_and_encrypted_callback(api, monkeypatch):
    client, tenants = api
    tenant_id, owner_token, _ = _signup_and_login(client, tenants, monkeypatch)
    client.headers["Authorization"] = f"Bearer {owner_token}"
    monkeypatch.setenv("GOOGLE_OAUTH_CLIENT_ID", "test-client")
    monkeypatch.setenv("GOOGLE_OAUTH_CLIENT_SECRET", "test-secret")
    monkeypatch.setenv(
        "GOOGLE_OAUTH_REDIRECT_URI",
        "http://localhost:8001/auth/calendar/google/callback",
    )
    monkeypatch.setenv("GOOGLE_OAUTH_STATE_SECRET", "a-test-only-state-signing-secret")

    connect = client.get(f"/admin/tenants/{tenant_id}/calendar/google/connect")
    assert connect.status_code == 200, connect.text
    auth_params = parse_qs(urlsplit(connect.json()["authorization_url"]).query)
    assert auth_params["access_type"] == ["offline"]
    assert auth_params["response_type"] == ["code"]
    state = auth_params["state"][0]

    class FakeResponse:
        status_code = 200
        is_error = False

        def json(self):
            return {"access_token": "access-secret", "refresh_token": "refresh-secret"}

    class FakeClient:
        def __init__(self, **_kwargs):
            pass

        async def __aenter__(self):
            return self

        async def __aexit__(self, *_args):
            return None

        async def post(self, url, data, headers):
            assert url == "https://oauth2.googleapis.com/token"
            assert data["grant_type"] == "authorization_code"
            assert headers["Accept"] == "application/json"
            return FakeResponse()

    monkeypatch.setattr(calendar_oauth.httpx, "AsyncClient", FakeClient)
    callback = client.get(
        "/auth/calendar/google/callback",
        params={"state": state, "code": "authorization-code"},
        follow_redirects=False,
    )
    assert callback.status_code == 303
    assert callback.headers["location"].endswith("/settings?calendar=connected")
    assert client.get(
        f"/admin/tenants/{tenant_id}/calendar/google/status"
    ).json() == {"provider": "google_calendar", "connected": True}
    assert client.get(
        "/auth/calendar/google/callback",
        params={"state": state, "code": "authorization-code"},
        follow_redirects=False,
    ).status_code == 400

    async def credential_is_encrypted() -> bool:
        async with tenant_connection(tenant_id) as conn:
            ciphertext = await conn.fetchval(
                "SELECT encrypted_calendar_credentials FROM tenant_settings WHERE tenant_id = $1",
                tenant_id,
            )
        return b"refresh-secret" not in ciphertext

    assert client.portal.call(credential_is_encrypted)


def test_webhook_signing_delivery_log_and_retry(api, monkeypatch):
    client, tenants = api
    tenant_id, owner_token, _ = _signup_and_login(client, tenants, monkeypatch)
    client.headers["Authorization"] = f"Bearer {owner_token}"
    monkeypatch.setattr(webhooks, "validate_webhook_url", lambda value: value)
    monkeypatch.setattr(event_dispatcher, "validate_webhook_url", lambda value: value)

    create = client.post(
        f"/admin/tenants/{tenant_id}/webhooks",
        json={
            "target_url": "https://hooks.example.com/propview",
            "events": ["lead.created", "lead.qualified", "appointment.booked", "call.completed"],
        },
    )
    assert create.status_code == 200, create.text
    webhook_id = create.json()["id"]
    signing_secret = create.json()["signing_secret"]

    async def seed_events() -> tuple[int, int]:
        async with tenant_connection(tenant_id) as conn:
            contact_id = await conn.fetchval(
                """
                INSERT INTO contacts (tenant_id, full_name, phone_number)
                VALUES ($1, 'Webhook Caller', $2) RETURNING id
                """,
                tenant_id,
                f"+1555{uuid.uuid4().int % 10**7:07d}",
            )
            lead_id = await conn.fetchval(
                """
                INSERT INTO leads (tenant_id, contact_id, priority, status)
                VALUES ($1, $2, 'high', 'new') RETURNING id
                """,
                tenant_id,
                contact_id,
            )
            appointment_id = await conn.fetchval(
                """
                INSERT INTO appointments (tenant_id, lead_id, scheduled_at)
                VALUES ($1, $2, now() + interval '2 days') RETURNING id
                """,
                tenant_id,
                lead_id,
            )
            await conn.execute(
                """
                INSERT INTO interactions (tenant_id, contact_id, lead_id, call_id, channel)
                VALUES ($1, $2, $3, $4, 'voice')
                """,
                tenant_id,
                contact_id,
                lead_id,
                f"webhook-call-{uuid.uuid4().hex}",
            )
        return lead_id, appointment_id

    lead_id, _ = client.portal.call(seed_events)
    assert client.patch(
        f"/admin/tenants/{tenant_id}/leads/{lead_id}",
        json={"status": "qualified"},
    ).status_code == 200

    async def read_outbox():
        async with tenant_connection(tenant_id) as conn:
            deliveries = await conn.fetch(
                """
                SELECT id, event_name, status, attempts FROM webhook_deliveries
                WHERE tenant_id = $1 AND webhook_id = $2 ORDER BY id
                """,
                tenant_id,
                webhook_id,
            )
            email_count = await conn.fetchval(
                "SELECT count(*) FROM email_outbox WHERE tenant_id = $1",
                tenant_id,
            )
            encrypted_secret = await conn.fetchval(
                "SELECT encrypted_signing_secret FROM tenant_webhooks WHERE tenant_id = $1 AND id = $2",
                tenant_id,
                webhook_id,
            )
        return deliveries, email_count, encrypted_secret

    deliveries, email_count, encrypted_secret = client.portal.call(read_outbox)
    assert {row["event_name"] for row in deliveries} == {
        "lead.created", "lead.qualified", "appointment.booked", "call.completed"
    }
    assert email_count >= 2
    assert signing_secret.encode() not in encrypted_secret
    assert client.get(
        f"/admin/tenants/{tenant_id}/webhooks/{webhook_id}/deliveries"
    ).status_code == 200

    class FakeWebhookClient:
        def __init__(self):
            self.statuses = [503, 204]
            self.headers = []

        async def post(self, _url, content, headers):
            self.headers.append(headers)
            assert content
            return type("Response", (), {"status_code": self.statuses.pop(0)})()

    async def accept_email(*_args):
        return None

    monkeypatch.setattr(event_dispatcher, "send_email", accept_email)
    fake_client = FakeWebhookClient()
    first = client.portal.call(
        event_dispatcher.dispatch_tenant, tenant_id, fake_client, 1
    )
    assert first["webhook_attempts"] == 1
    first_delivery_id = deliveries[0]["id"]

    async def make_retry_due():
        async with tenant_connection(tenant_id) as conn:
            await conn.execute(
                "UPDATE webhook_deliveries SET next_attempt_at = now() - interval '1 second' WHERE tenant_id = $1 AND id = $2",
                tenant_id,
                first_delivery_id,
            )

    client.portal.call(make_retry_due)
    second = client.portal.call(
        event_dispatcher.dispatch_tenant, tenant_id, fake_client, 1
    )
    assert second["webhook_attempts"] == 1
    assert fake_client.headers[0]["X-Propview-Signature"].startswith("sha256=")

    async def delivered_state() -> tuple[str, int]:
        async with tenant_connection(tenant_id) as conn:
            row = await conn.fetchrow(
                "SELECT status, attempts FROM webhook_deliveries WHERE tenant_id = $1 AND id = $2",
                tenant_id,
                first_delivery_id,
            )
        return row["status"], row["attempts"]

    assert client.portal.call(delivered_state) == ("delivered", 2)
