"""
PROP-302: Tests for the listing ingestion script against real Postgres
and the real Gemini embeddings API (needs GEMINI_API_KEY).

Run: DATABASE_URL=postgresql://propview_app:devpassword@localhost/propview_dev \
     GEMINI_API_KEY=... python -m pytest tests/ -v
"""

import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import asyncpg
import pytest
import pytest_asyncio

from ingest_listings import chunk_text, ingest_directory

DATABASE_URL = os.environ.get("DATABASE_URL", "postgresql://propview_app:devpassword@localhost/propview_dev")
TEST_TENANT = "test-ingestion"


def test_chunk_text_collapses_whitespace_and_respects_size():
    text = "word " * 300  # 1500 chars
    chunks = chunk_text(text, size=500, overlap=50)
    assert all(len(c) <= 500 for c in chunks)
    assert len(chunks) > 1


def test_chunk_text_empty_input_returns_no_chunks():
    assert chunk_text("   \n\n  ") == []


@pytest_asyncio.fixture
async def cleanup():
    yield
    conn = await asyncpg.connect(DATABASE_URL)
    await conn.execute("SELECT set_config('app.tenant_id', $1, false)", TEST_TENANT)
    await conn.execute("DELETE FROM knowledge_base_chunks WHERE tenant_id = $1", TEST_TENANT)
    await conn.close()


@pytest.mark.asyncio
@pytest.mark.skipif(not os.environ.get("GEMINI_API_KEY"), reason="needs a real Gemini API key")
async def test_ingest_directory_embeds_and_stores_real_chunks(tmp_path, cleanup):
    (tmp_path / "faq.txt").write_text(
        "What is the HOA fee? The HOA fee for this property is $200 per month, "
        "covering landscaping, pool maintenance, and community security."
    )

    total = await ingest_directory(
        directory=tmp_path,
        source_type="faq",
        tenant_id=TEST_TENANT,
        project_id=None,
        property_id=None,
        database_url=DATABASE_URL,
    )
    assert total == 1

    conn = await asyncpg.connect(DATABASE_URL)
    await conn.execute("SELECT set_config('app.tenant_id', $1, false)", TEST_TENANT)
    row = await conn.fetchrow("SELECT source_type, source_name, content FROM knowledge_base_chunks WHERE tenant_id = $1", TEST_TENANT)
    await conn.close()

    assert row["source_type"] == "faq"
    assert row["source_name"] == "faq.txt"
    assert "HOA fee" in row["content"]


@pytest.mark.asyncio
@pytest.mark.skipif(not os.environ.get("GEMINI_API_KEY"), reason="needs a real Gemini API key")
async def test_semantic_search_finds_differently_worded_query(tmp_path, cleanup):
    """The real point of embeddings: a query with no words in common should
    still retrieve the right chunk via semantic similarity."""
    (tmp_path / "faq.txt").write_text(
        "What is the HOA fee? The HOA fee for this property is $200 per month."
    )
    await ingest_directory(tmp_path, "faq", TEST_TENANT, None, None, DATABASE_URL)

    from google import genai
    from google.genai import types
    from pgvector.asyncpg import register_vector

    client = genai.Client(api_key=os.environ["GEMINI_API_KEY"])
    query_embedding = client.models.embed_content(
        model="gemini-embedding-001",
        contents="How much are the monthly homeowners association dues?",
        config=types.EmbedContentConfig(output_dimensionality=768),
    ).embeddings[0].values

    conn = await asyncpg.connect(DATABASE_URL)
    await register_vector(conn)
    await conn.execute("SELECT set_config('app.tenant_id', $1, false)", TEST_TENANT)
    row = await conn.fetchrow(
        "SELECT content, embedding <=> $1 AS distance FROM knowledge_base_chunks "
        "WHERE tenant_id = $2 ORDER BY distance LIMIT 1",
        query_embedding,
        TEST_TENANT,
    )
    await conn.close()

    assert "HOA fee" in row["content"]
    assert row["distance"] < 0.5  # semantically close despite no shared keywords
