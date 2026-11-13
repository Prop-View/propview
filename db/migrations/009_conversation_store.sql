-- Structured conversation storage for ML training and algorithm improvement.
--
-- interactions.transcript (003) stores a PII-masked text blob per call;
-- these tables store the structured, per-turn data that ML pipelines need:
-- who said what, when, which tools fired, how the call performed.
--
-- pgvector is already enabled (002). Embedding dimension 768 matches
-- the gemini-embedding-001 config used by db/ingestion/.

-- Per-utterance record: the structured version of what
-- ConversationContextStore (Redis, ephemeral) holds mid-call.
CREATE TABLE IF NOT EXISTS conversation_turns (
    id              BIGSERIAL PRIMARY KEY,
    tenant_id       TEXT NOT NULL DEFAULT 'default',
    call_id         TEXT NOT NULL,
    turn_index      INTEGER NOT NULL,
    speaker         TEXT NOT NULL CHECK (speaker IN ('caller', 'agent')),
    text            TEXT NOT NULL,
    interrupted     BOOLEAN NOT NULL DEFAULT FALSE,
    timestamp_ms    DOUBLE PRECISION NOT NULL,
    embedding       vector(768),
    created_at      TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE INDEX IF NOT EXISTS idx_conv_turns_tenant ON conversation_turns (tenant_id);
CREATE INDEX IF NOT EXISTS idx_conv_turns_call_id ON conversation_turns (call_id);
CREATE INDEX IF NOT EXISTS idx_conv_turns_speaker ON conversation_turns (tenant_id, speaker);
CREATE INDEX IF NOT EXISTS idx_conv_turns_embedding
    ON conversation_turns USING ivfflat (embedding vector_cosine_ops) WITH (lists = 10)
    WHERE embedding IS NOT NULL;

-- Every tool call the AI made during a conversation.
CREATE TABLE IF NOT EXISTS tool_invocations (
    id              BIGSERIAL PRIMARY KEY,
    tenant_id       TEXT NOT NULL DEFAULT 'default',
    call_id         TEXT NOT NULL,
    turn_index      INTEGER,
    tool_name       TEXT NOT NULL,
    input_params    JSONB NOT NULL DEFAULT '{}',
    output_result   JSONB,
    error           TEXT,
    latency_ms      DOUBLE PRECISION,
    success         BOOLEAN NOT NULL DEFAULT TRUE,
    created_at      TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE INDEX IF NOT EXISTS idx_tool_inv_tenant ON tool_invocations (tenant_id);
CREATE INDEX IF NOT EXISTS idx_tool_inv_call_id ON tool_invocations (call_id);
CREATE INDEX IF NOT EXISTS idx_tool_inv_tool_name ON tool_invocations (tenant_id, tool_name);

-- Aggregated per-call analytics for scoring and trend analysis.
CREATE TABLE IF NOT EXISTS call_analytics (
    id                      BIGSERIAL PRIMARY KEY,
    tenant_id               TEXT NOT NULL DEFAULT 'default',
    call_id                 TEXT NOT NULL UNIQUE,
    total_turns             INTEGER NOT NULL DEFAULT 0,
    caller_turns            INTEGER NOT NULL DEFAULT 0,
    agent_turns             INTEGER NOT NULL DEFAULT 0,
    duration_seconds        INTEGER,
    tools_used              JSONB NOT NULL DEFAULT '[]',
    barge_in_count          INTEGER NOT NULL DEFAULT 0,
    outcome                 TEXT CHECK (outcome IN (
        'booked', 'qualified', 'dropped', 'transferred', 'nurture', 'unknown'
    )),
    lead_id                 BIGINT REFERENCES leads(id) ON DELETE SET NULL,
    created_at              TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE INDEX IF NOT EXISTS idx_call_analytics_tenant ON call_analytics (tenant_id);
CREATE INDEX IF NOT EXISTS idx_call_analytics_outcome ON call_analytics (tenant_id, outcome);
CREATE INDEX IF NOT EXISTS idx_call_analytics_created ON call_analytics (tenant_id, created_at);

-- RLS: same pattern as 004_row_level_security.sql
DO $$
DECLARE
    tbl TEXT;
BEGIN
    FOREACH tbl IN ARRAY ARRAY['conversation_turns', 'tool_invocations', 'call_analytics']
    LOOP
        EXECUTE format('ALTER TABLE %I ENABLE ROW LEVEL SECURITY', tbl);
        EXECUTE format('ALTER TABLE %I FORCE ROW LEVEL SECURITY', tbl);
        EXECUTE format('DROP POLICY IF EXISTS tenant_isolation ON %I', tbl);
        EXECUTE format(
            'CREATE POLICY tenant_isolation ON %I
                USING (tenant_id = current_setting(''app.tenant_id'', true))
                WITH CHECK (tenant_id = current_setting(''app.tenant_id'', true))',
            tbl
        );
    END LOOP;
END $$;
