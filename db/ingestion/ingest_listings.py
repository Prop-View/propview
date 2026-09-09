"""
PROP-302: Listing ingestion -- PDF/text files -> chunks -> Gemini
embeddings -> knowledge_base_chunks (PROP-301's pgvector table).

Usage:
    python ingest_listings.py <directory> --source-type brochure [--project-id 1] [--property-id 1] [--tenant-id default]

Reads every .txt/.md/.pdf file in <directory>, splits into ~500-character
chunks, embeds each with gemini-embedding-001 (768 dims, matching
db/migrations/002_knowledge_base_pgvector.sql), and inserts them.
"""

from __future__ import annotations

import argparse
import asyncio
import os
from pathlib import Path

import asyncpg
from dotenv import load_dotenv
from google import genai
from google.genai import types
from pgvector.asyncpg import register_vector
from pypdf import PdfReader

load_dotenv()

EMBEDDING_MODEL = "gemini-embedding-001"
EMBEDDING_DIMENSIONS = 768
CHUNK_SIZE_CHARS = 500
CHUNK_OVERLAP_CHARS = 50


def extract_text(path: Path) -> str:
    if path.suffix.lower() == ".pdf":
        reader = PdfReader(str(path))
        return "\n".join(page.extract_text() or "" for page in reader.pages)
    return path.read_text(encoding="utf-8", errors="ignore")


def chunk_text(text: str, size: int = CHUNK_SIZE_CHARS, overlap: int = CHUNK_OVERLAP_CHARS) -> list[str]:
    text = " ".join(text.split())  # collapse whitespace/newlines
    if not text:
        return []
    chunks = []
    start = 0
    while start < len(text):
        end = start + size
        chunks.append(text[start:end])
        start = end - overlap
    return chunks


def embed_chunks(client: genai.Client, chunks: list[str]) -> list[list[float]]:
    config = types.EmbedContentConfig(output_dimensionality=EMBEDDING_DIMENSIONS)
    result = client.models.embed_content(model=EMBEDDING_MODEL, contents=chunks, config=config)
    return [e.values for e in result.embeddings]


async def ingest_directory(
    directory: Path,
    source_type: str,
    tenant_id: str,
    project_id: int | None,
    property_id: int | None,
    database_url: str,
) -> int:
    client = genai.Client(api_key=os.environ["GEMINI_API_KEY"])
    conn = await asyncpg.connect(database_url)
    await register_vector(conn)
    await conn.execute("SELECT set_config('app.tenant_id', $1, false)", tenant_id)

    total_chunks = 0
    files = [p for p in directory.iterdir() if p.suffix.lower() in (".txt", ".md", ".pdf")]
    if not files:
        print(f"No .txt/.md/.pdf files found in {directory}")

    for path in files:
        text = extract_text(path)
        chunks = chunk_text(text)
        if not chunks:
            print(f"  {path.name}: no extractable text, skipping")
            continue

        embeddings = embed_chunks(client, chunks)
        for content, embedding in zip(chunks, embeddings):
            await conn.execute(
                """
                INSERT INTO knowledge_base_chunks
                    (tenant_id, project_id, property_id, source_type, source_name, content, embedding)
                VALUES ($1, $2, $3, $4, $5, $6, $7)
                """,
                tenant_id,
                project_id,
                property_id,
                source_type,
                path.name,
                content,
                embedding,
            )
        print(f"  {path.name}: {len(chunks)} chunks ingested")
        total_chunks += len(chunks)

    await conn.close()
    return total_chunks


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("directory", type=Path)
    parser.add_argument("--source-type", required=True, choices=["faq", "policy", "brochure", "transcript", "other"])
    parser.add_argument("--project-id", type=int, default=None)
    parser.add_argument("--property-id", type=int, default=None)
    parser.add_argument("--tenant-id", default="default")
    parser.add_argument("--database-url", default=os.environ.get("DATABASE_URL", "postgresql://localhost/propview_dev"))
    args = parser.parse_args()

    if not args.directory.is_dir():
        parser.error(f"{args.directory} is not a directory")

    total = asyncio.run(
        ingest_directory(
            args.directory, args.source_type, args.tenant_id, args.project_id, args.property_id, args.database_url
        )
    )
    print(f"Done: {total} chunks ingested.")


if __name__ == "__main__":
    main()
