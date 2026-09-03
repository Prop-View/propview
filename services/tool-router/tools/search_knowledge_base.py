"""
search_knowledge_base tool -- semantic search over db/ingestion's
pgvector-embedded FAQs/brochures/policies (PROP-301/302), completing the
RAG loop those tickets set up but didn't wire into a callable tool.

Embeds the query with the same model/dimensionality db/ingestion uses
(gemini-embedding-001, output_dimensionality=768) so the vectors are
comparable -- a mismatch here would silently make every search return
poor/random matches, not an error, so this MUST stay in sync with
db/ingestion/ingest_listings.py's EMBEDDING_MODEL/EMBEDDING_DIMENSIONS.
"""

from __future__ import annotations

import os

import asyncpg
from google import genai
from google.genai import types
from pydantic import BaseModel, Field

EMBEDDING_MODEL = "gemini-embedding-001"
EMBEDDING_DIMENSIONS = 768

_client: genai.Client | None = None


def _get_client() -> genai.Client:
    global _client
    if _client is None:
        _client = genai.Client(api_key=os.environ["GEMINI_API_KEY"])
    return _client


class SearchKnowledgeBaseArgs(BaseModel):
    query: str
    limit: int = Field(3, ge=1, le=10)


async def search_knowledge_base(
    connection: asyncpg.Connection, args: SearchKnowledgeBaseArgs, tenant_id: str = "default"
) -> list[dict]:
    embedding = (
        _get_client()
        .models.embed_content(
            model=EMBEDDING_MODEL,
            contents=args.query,
            config=types.EmbedContentConfig(output_dimensionality=EMBEDDING_DIMENSIONS),
        )
        .embeddings[0]
        .values
    )

    rows = await connection.fetch(
        """
        SELECT content, source_type, source_name, embedding <=> $2 AS distance
        FROM knowledge_base_chunks
        WHERE tenant_id = $1
        ORDER BY distance
        LIMIT $3
        """,
        tenant_id,
        embedding,
        args.limit,
    )
    return [
        {"content": r["content"], "source_type": r["source_type"], "source_name": r["source_name"]} for r in rows
    ]
