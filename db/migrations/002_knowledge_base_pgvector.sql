-- PROP-301: pgvector-backed knowledge base for RAG over brochures/FAQs/policies.
--
-- Embedding dimension is 768. Originally documented as matching
-- text-embedding-004, but that model doesn't exist for the account this
-- was built against -- db/ingestion/ (PROP-302) uses gemini-embedding-001
-- with output_dimensionality=768 explicitly (its default is 3072).
-- pgvector enforces this column's fixed dimension at insert time, so a
-- mismatch fails loudly rather than silently corrupting data.

CREATE EXTENSION IF NOT EXISTS vector;

CREATE TABLE IF NOT EXISTS knowledge_base_chunks (
    id            BIGSERIAL PRIMARY KEY,
    tenant_id     TEXT NOT NULL DEFAULT 'default',
    project_id    BIGINT REFERENCES projects(id) ON DELETE CASCADE,
    property_id   BIGINT REFERENCES properties(id) ON DELETE CASCADE,
    source_type   TEXT NOT NULL CHECK (source_type IN ('faq', 'policy', 'brochure', 'transcript', 'other')),
    source_name   TEXT,                      -- original filename/URL, for traceability
    content       TEXT NOT NULL,             -- the chunked text
    embedding     vector(768) NOT NULL,
    created_at    TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE INDEX IF NOT EXISTS idx_kb_chunks_tenant ON knowledge_base_chunks (tenant_id);

-- IVFFlat needs data present to build well (lists tuned for small dev
-- datasets); rebuild with a higher `lists` value once real volume exists.
CREATE INDEX IF NOT EXISTS idx_kb_chunks_embedding
    ON knowledge_base_chunks USING ivfflat (embedding vector_cosine_ops) WITH (lists = 10);
