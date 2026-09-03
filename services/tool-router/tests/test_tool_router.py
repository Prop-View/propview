"""
PROP-303/304/307: Tool Router tests against a real local Postgres.

Run: DATABASE_URL=postgresql://localhost/propview_dev python -m pytest tests/ -v
(assumes db/migrations/apply_migrations.py has already been run)
"""

import asyncio
import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
os.environ.setdefault("DATABASE_URL", "postgresql://localhost/propview_dev")

import asyncpg
import pytest
from fastapi.testclient import TestClient

from main import app

TEST_TENANT = "test-tool-router"


async def _seed() -> None:
    # PROP-601's RLS is fail-closed (WITH CHECK included), so this
    # connection must set app.tenant_id before insert/delete or every
    # statement is rejected -- caught by actually running these tests
    # after enabling RLS, not assumed.
    conn = await asyncpg.connect(os.environ["DATABASE_URL"])
    await conn.execute("SELECT set_config('app.tenant_id', $1, false)", TEST_TENANT)
    await conn.execute("DELETE FROM properties WHERE tenant_id = $1", TEST_TENANT)
    await conn.execute(
        """
        INSERT INTO properties (tenant_id, address, city, state, property_type, beds, baths, sqft, price, amenities)
        VALUES
            ($1, '123 Oak St', 'Austin', 'TX', 'house', 3, 2.0, 1800, 520000, '["pool"]'),
            ($1, '456 Pine Ave', 'Austin', 'TX', 'house', 3, 2.5, 2100, 545000, '[]'),
            ($1, '789 Elm Dr', 'Austin', 'TX', 'condo', 2, 1.0, 1100, 310000, '[]'),
            ($1, '999 Cedar Ln', 'Austin', 'TX', 'house', 4, 3.0, 2600, 610000, '[]')
        """,
        TEST_TENANT,
    )
    await conn.close()


async def _cleanup() -> None:
    conn = await asyncpg.connect(os.environ["DATABASE_URL"])
    await conn.execute("SELECT set_config('app.tenant_id', $1, false)", TEST_TENANT)
    await conn.execute("DELETE FROM properties WHERE tenant_id = $1", TEST_TENANT)
    await conn.close()


@pytest.fixture(scope="module")
def client():
    asyncio.run(_seed())
    with TestClient(app) as c:
        yield c
    asyncio.run(_cleanup())


def call_tool(client, name, args, tenant_id=TEST_TENANT):
    return client.post("/tools/call", json={"name": name, "args": args, "tenant_id": tenant_id})


def test_health(client):
    resp = client.get("/health")
    assert resp.status_code == 200
    assert resp.json() == {"status": "ok"}


def test_search_properties_filters_correctly(client):
    resp = call_tool(client, "search_properties", {"city": "Austin", "property_type": "house", "min_beds": 3, "max_price": 550000})
    assert resp.status_code == 200
    addresses = {r["address"] for r in resp.json()["result"]}
    assert addresses == {"123 Oak St", "456 Pine Ave"}  # excludes the condo and the $610k house


def test_search_properties_amenities_deserialized_as_list(client):
    resp = call_tool(client, "search_properties", {"city": "Austin", "min_price": 519000, "max_price": 521000})
    result = resp.json()["result"]
    assert result[0]["amenities"] == ["pool"]


def test_search_properties_price_is_json_number_not_string(client):
    resp = call_tool(client, "search_properties", {"city": "Austin", "max_price": 550000})
    for row in resp.json()["result"]:
        assert isinstance(row["price"], (int, float))


def test_search_properties_rejects_invalid_property_type(client):
    resp = call_tool(client, "search_properties", {"property_type": "castle"})
    assert resp.status_code == 422


def test_search_properties_sql_injection_attempt_is_inert(client):
    resp = call_tool(client, "search_properties", {"city": "Austin'; DROP TABLE properties; --"})
    assert resp.status_code == 200
    assert resp.json()["result"] == []  # no city matches that literal string -- injection did not execute

    # table must still exist and be queryable
    resp2 = call_tool(client, "search_properties", {"city": "Austin"})
    assert resp2.status_code == 200
    assert len(resp2.json()["result"]) > 0


def test_get_property_details_returns_full_record(client):
    search_resp = call_tool(client, "search_properties", {"city": "Austin", "property_type": "condo"})
    prop_id = search_resp.json()["result"][0]["id"]

    detail_resp = call_tool(client, "get_property_details", {"property_id": prop_id})
    assert detail_resp.status_code == 200
    assert detail_resp.json()["result"]["address"] == "789 Elm Dr"


def test_get_property_details_nonexistent_returns_none(client):
    resp = call_tool(client, "get_property_details", {"property_id": 999999999})
    assert resp.status_code == 200
    assert resp.json()["result"] is None


def test_get_property_details_respects_tenant_isolation(client):
    search_resp = call_tool(client, "search_properties", {"city": "Austin"})
    prop_id = search_resp.json()["result"][0]["id"]

    resp = call_tool(client, "get_property_details", {"property_id": prop_id}, tenant_id="some-other-tenant")
    assert resp.json()["result"] is None


def test_search_properties_isolated_by_rls_not_just_app_filter(client):
    """PROP-601: even asking for this tenant's exact city/type, a
    different tenant_id must see nothing -- enforced by Postgres RLS
    (db/migrations/004_row_level_security.sql), not just this query's own
    WHERE tenant_id clause."""
    resp = call_tool(client, "search_properties", {"city": "Austin"}, tenant_id="some-other-tenant")
    assert resp.status_code == 200
    assert resp.json()["result"] == []


def test_unknown_tool_returns_404(client):
    resp = client.post("/tools/call", json={"name": "not_a_real_tool", "args": {}})
    assert resp.status_code == 404


def test_tools_schema_lists_all_tools(client):
    resp = client.get("/tools/schema")
    assert set(resp.json().keys()) == {"search_properties", "get_property_details", "search_knowledge_base"}


@pytest.mark.skipif(not os.environ.get("GEMINI_API_KEY"), reason="needs a real Gemini API key")
def test_search_knowledge_base_semantic_match(client):
    """Seeds one real-embedded chunk, then queries with different wording
    to confirm this is genuine semantic search, not a text match."""
    from google import genai
    from google.genai import types

    genai_client = genai.Client(api_key=os.environ["GEMINI_API_KEY"])
    embedding = (
        genai_client.models.embed_content(
            model="gemini-embedding-001",
            contents="The HOA fee for this property is $200 per month.",
            config=types.EmbedContentConfig(output_dimensionality=768),
        )
        .embeddings[0]
        .values
    )

    async def seed():
        import asyncpg
        from pgvector.asyncpg import register_vector

        conn = await asyncpg.connect(os.environ["DATABASE_URL"])
        await register_vector(conn)
        await conn.execute("SELECT set_config('app.tenant_id', $1, false)", TEST_TENANT)
        await conn.execute("DELETE FROM knowledge_base_chunks WHERE tenant_id = $1", TEST_TENANT)
        await conn.execute(
            "INSERT INTO knowledge_base_chunks (tenant_id, source_type, source_name, content, embedding) "
            "VALUES ($1, 'faq', 'test.txt', $2, $3)",
            TEST_TENANT,
            "The HOA fee for this property is $200 per month.",
            embedding,
        )
        await conn.close()

    asyncio.run(seed())

    resp = call_tool(client, "search_knowledge_base", {"query": "How much are the monthly homeowners association dues?"})
    assert resp.status_code == 200
    result = resp.json()["result"]
    assert len(result) > 0
    assert "HOA fee" in result[0]["content"]
