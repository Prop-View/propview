"""Tenant-scoped wrapper around the shared knowledge-base ingestion helpers."""

from __future__ import annotations

import asyncio
import importlib.util
import os
import tempfile
from functools import lru_cache
from pathlib import Path

from fastapi import HTTPException, UploadFile
from google import genai
from google.genai.errors import APIError

from db import tenant_connection

MAX_DOCUMENT_BYTES = 10 * 1024 * 1024
ALLOWED_SUFFIXES = {".txt", ".md", ".pdf"}
INGESTION_SCRIPT = Path(__file__).resolve().parents[2] / "db" / "ingestion" / "ingest_listings.py"


@lru_cache(maxsize=1)
def _ingestion_helpers():
    spec = importlib.util.spec_from_file_location("propview_ingest_listings", INGESTION_SCRIPT)
    if spec is None or spec.loader is None:
        raise RuntimeError(f"Unable to load ingestion helpers from {INGESTION_SCRIPT}")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


async def ingest_document(
    tenant_id: str,
    upload: UploadFile,
    source_type: str,
    project_id: int | None,
    property_id: int | None,
) -> int:
    suffix = Path(upload.filename or "").suffix.lower()
    if suffix not in ALLOWED_SUFFIXES:
        raise HTTPException(status_code=415, detail="Only PDF, TXT, and Markdown files are supported")
    if not os.environ.get("GEMINI_API_KEY"):
        raise HTTPException(status_code=503, detail="GEMINI_API_KEY is not configured")

    contents = await upload.read(MAX_DOCUMENT_BYTES + 1)
    if not contents:
        raise HTTPException(status_code=400, detail="Document is empty")
    if len(contents) > MAX_DOCUMENT_BYTES:
        raise HTTPException(status_code=413, detail="Document exceeds the 10 MiB limit")

    helpers = _ingestion_helpers()
    with tempfile.TemporaryDirectory() as temp_dir:
        temp_path = Path(temp_dir) / f"document{suffix}"
        temp_path.write_bytes(contents)
        chunks = helpers.chunk_text(helpers.extract_text(temp_path))
    if not chunks:
        raise HTTPException(status_code=422, detail="Document contains no extractable text")

    if project_id is not None or property_id is not None:
        async with tenant_connection(tenant_id) as conn:
            if project_id is not None:
                exists = await conn.fetchval(
                    "SELECT EXISTS(SELECT 1 FROM projects WHERE tenant_id = $1 AND id = $2)",
                    tenant_id,
                    project_id,
                )
                if not exists:
                    raise HTTPException(status_code=404, detail="Project not found")
            if property_id is not None:
                exists = await conn.fetchval(
                    "SELECT EXISTS(SELECT 1 FROM properties WHERE tenant_id = $1 AND id = $2)",
                    tenant_id,
                    property_id,
                )
                if not exists:
                    raise HTTPException(status_code=404, detail="Property not found")

    client = genai.Client(api_key=os.environ["GEMINI_API_KEY"])
    try:
        embeddings = await asyncio.to_thread(helpers.embed_chunks, client, chunks)
    except APIError as exc:
        raise HTTPException(status_code=502, detail="Embedding provider rejected the document") from exc

    async with tenant_connection(tenant_id) as conn:
        for content, embedding in zip(chunks, embeddings, strict=True):
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
                upload.filename,
                content,
                embedding,
            )
    return len(chunks)
