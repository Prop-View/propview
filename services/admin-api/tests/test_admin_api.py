"""
PROP-602: Tenant Admin API tests against real Postgres.

Run: DATABASE_URL=postgresql://propview_app:devpassword@localhost/propview_dev \
     ENCRYPTION_KEY=<fernet key> python -m pytest tests/ -v
"""

import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
os.environ.setdefault("DATABASE_URL", "postgresql://propview_app:devpassword@localhost/propview_dev")
os.environ.setdefault("ENCRYPTION_KEY", "FG6ZzLBZnosF1kPSMHKpkDwpdPrinkzVBQ5I9CdMHEE=")  # test-only key

import asyncio

import asyncpg
import pytest
from fastapi.testclient import TestClient

from main import app

TEST_TENANT = "test-admin-api"


async def _cleanup() -> None:
    conn = await asyncpg.connect(os.environ["DATABASE_URL"])
    await conn.execute("SELECT set_config('app.tenant_id', $1, false)", TEST_TENANT)
    await conn.execute("DELETE FROM properties WHERE tenant_id = $1", TEST_TENANT)
    await conn.execute("DELETE FROM tenant_settings WHERE tenant_id = $1", TEST_TENANT)
    await conn.close()


@pytest.fixture
def client():
    asyncio.run(_cleanup())
    with TestClient(app) as c:
        yield c
    asyncio.run(_cleanup())


def test_health(client):
    resp = client.get("/health")
    assert resp.status_code == 200


def test_upload_listings_inserts_real_rows(client):
    resp = client.post(
        f"/admin/tenants/{TEST_TENANT}/listings",
        json={
            "listings": [
                {
                    "address": "1 Test Ave",
                    "city": "Austin",
                    "state": "TX",
                    "property_type": "house",
                    "price": 400000,
                    "amenities": ["pool", "garage"],
                },
                {
                    "address": "2 Test Ave",
                    "city": "Austin",
                    "state": "TX",
                    "property_type": "condo",
                    "price": 250000,
                },
            ]
        },
    )
    assert resp.status_code == 200
    body = resp.json()
    assert body["inserted"] == 2
    assert len(body["ids"]) == 2


def test_upload_listings_rejects_empty_list(client):
    resp = client.post(f"/admin/tenants/{TEST_TENANT}/listings", json={"listings": []})
    assert resp.status_code == 400


def test_upload_listings_rejects_invalid_property_type(client):
    resp = client.post(
        f"/admin/tenants/{TEST_TENANT}/listings",
        json={"listings": [{"address": "3 Test Ave", "city": "Austin", "state": "TX", "property_type": "castle", "price": 1}]},
    )
    assert resp.status_code == 422


def test_uploaded_listing_is_scoped_to_its_tenant(client):
    client.post(
        f"/admin/tenants/{TEST_TENANT}/listings",
        json={"listings": [{"address": "4 Test Ave", "city": "Austin", "state": "TX", "property_type": "house", "price": 500000}]},
    )

    async def check_other_tenant_sees_nothing():
        conn = await asyncpg.connect(os.environ["DATABASE_URL"])
        await conn.execute("SELECT set_config('app.tenant_id', 'some-other-tenant', false)")
        rows = await conn.fetch("SELECT * FROM properties WHERE address = '4 Test Ave'")
        await conn.close()
        return rows

    assert asyncio.run(check_other_tenant_sees_nothing()) == []


def test_calendar_credentials_roundtrip_encrypted(client):
    put_resp = client.put(
        f"/admin/tenants/{TEST_TENANT}/calendar-credentials",
        json={"provider": "google_calendar", "credentials": {"access_token": "secret-token-xyz", "refresh_token": "refresh-abc"}},
    )
    assert put_resp.status_code == 200

    get_resp = client.get(f"/admin/tenants/{TEST_TENANT}/calendar-credentials")
    assert get_resp.status_code == 200
    body = get_resp.json()
    assert body["provider"] == "google_calendar"
    assert body["credentials"]["access_token"] == "secret-token-xyz"


def test_calendar_credentials_stored_encrypted_at_rest(client):
    client.put(
        f"/admin/tenants/{TEST_TENANT}/calendar-credentials",
        json={"provider": "google_calendar", "credentials": {"access_token": "should-not-appear-in-plaintext"}},
    )

    async def read_raw():
        conn = await asyncpg.connect(os.environ["DATABASE_URL"])
        await conn.execute("SELECT set_config('app.tenant_id', $1, false)", TEST_TENANT)
        row = await conn.fetchrow(
            "SELECT encrypted_calendar_credentials FROM tenant_settings WHERE tenant_id = $1", TEST_TENANT
        )
        await conn.close()
        return row["encrypted_calendar_credentials"]

    raw_bytes = asyncio.run(read_raw())
    assert b"should-not-appear-in-plaintext" not in raw_bytes


def test_calendar_credentials_upsert_overwrites(client):
    client.put(f"/admin/tenants/{TEST_TENANT}/calendar-credentials", json={"provider": "google_calendar", "credentials": {"v": 1}})
    client.put(f"/admin/tenants/{TEST_TENANT}/calendar-credentials", json={"provider": "google_calendar", "credentials": {"v": 2}})

    resp = client.get(f"/admin/tenants/{TEST_TENANT}/calendar-credentials")
    assert resp.json()["credentials"] == {"v": 2}


def test_calendar_credentials_missing_returns_nulls(client):
    resp = client.get(f"/admin/tenants/{TEST_TENANT}/calendar-credentials")
    assert resp.json() == {"provider": None, "credentials": None}
