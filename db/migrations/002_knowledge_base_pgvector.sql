-- PROP-301: pgvector-backed knowledge base for RAG over brochures/FAQs/policies.
--
-- Embedding dimension is 768 (matches Gemini's text-embedding-004 output).
-- This MUST match whatever embedding model PROP-302 (ingestion script,
-- not yet built) actually uses -- pgvector enforces the column's fixed
-- dimension at insert time, so a mismatch fails loudly rather than
-- silently corrupting data, but the model choice still needs to be
-- confirmed when PROP-302 is built.

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
