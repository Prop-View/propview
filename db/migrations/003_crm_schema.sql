-- PROP-401: CRM schema -- contacts, leads, appointments, interactions.
-- Extends the PROP-301 listings schema; leads reference properties,
-- appointments reference leads. tenant_id follows the same pattern as
-- 001/002 (default-scoped, RLS added later by PROP-601).

CREATE TABLE IF NOT EXISTS contacts (
    id            BIGSERIAL PRIMARY KEY,
    tenant_id     TEXT NOT NULL DEFAULT 'default',
    full_name     TEXT,
    phone_number  TEXT NOT NULL,
    email         TEXT,
    created_at    TIMESTAMPTZ NOT NULL DEFAULT now(),
    UNIQUE (tenant_id, phone_number)
);

-- BANT fields per services/prompts/bant_conversation_design.md.
-- Nullable throughout: qualification is partial by design (plan targets
-- >80% of FIELDS captured, not 100% of calls fully qualified).
CREATE TABLE IF NOT EXISTS leads (
    id                BIGSERIAL PRIMARY KEY,
    tenant_id         TEXT NOT NULL DEFAULT 'default',
    contact_id        BIGINT NOT NULL REFERENCES contacts(id) ON DELETE CASCADE,
    property_id       BIGINT REFERENCES properties(id) ON DELETE SET NULL,
    intent            TEXT CHECK (intent IN ('buy', 'sell', 'rent', 'browsing')),
    budget_min        NUMERIC(12,2),
    budget_max        NUMERIC(12,2),
    timeline          TEXT CHECK (timeline IN ('immediate', '1-3mo', '3-6mo', '6mo+', 'exploring')),
    decision_maker    TEXT CHECK (decision_maker IN ('solo', 'joint', 'other')),
    priority          TEXT CHECK (priority IN ('high', 'medium', 'low')),
    status            TEXT NOT NULL DEFAULT 'new' CHECK (status IN ('new', 'qualified', 'appointment_set', 'closed_won', 'closed_lost')),
    created_at        TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at        TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE INDEX IF NOT EXISTS idx_leads_tenant ON leads (tenant_id);
CREATE INDEX IF NOT EXISTS idx_leads_contact ON leads (contact_id);
CREATE INDEX IF NOT EXISTS idx_leads_priority ON leads (tenant_id, priority) WHERE status NOT IN ('closed_won', 'closed_lost');

CREATE TABLE IF NOT EXISTS appointments (
    id              BIGSERIAL PRIMARY KEY,
    tenant_id       TEXT NOT NULL DEFAULT 'default',
    lead_id         BIGINT NOT NULL REFERENCES leads(id) ON DELETE CASCADE,
    property_id     BIGINT REFERENCES properties(id) ON DELETE SET NULL,
    scheduled_at    TIMESTAMPTZ NOT NULL,
    status          TEXT NOT NULL DEFAULT 'scheduled' CHECK (status IN ('scheduled', 'confirmed', 'completed', 'cancelled', 'no_show')),
    agent_name      TEXT,
    confirmation_sms_sent_at TIMESTAMPTZ,
    created_at      TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE INDEX IF NOT EXISTS idx_appointments_tenant ON appointments (tenant_id);
CREATE INDEX IF NOT EXISTS idx_appointments_lead ON appointments (lead_id);
CREATE INDEX IF NOT EXISTS idx_appointments_schedule ON appointments (tenant_id, scheduled_at);

-- One row per call; ties back to services/orchestrator/session_store.py's
-- call_id (Redis is ephemeral/in-call state, this is the durable record).
CREATE TABLE IF NOT EXISTS interactions (
    id              BIGSERIAL PRIMARY KEY,
    tenant_id       TEXT NOT NULL DEFAULT 'default',
    contact_id      BIGINT REFERENCES contacts(id) ON DELETE SET NULL,
    lead_id         BIGINT REFERENCES leads(id) ON DELETE SET NULL,
    call_id         TEXT NOT NULL,          -- matches session_store.py's CallSession.call_id
    channel         TEXT NOT NULL DEFAULT 'voice' CHECK (channel IN ('voice', 'sms', 'whatsapp', 'email')),
    transcript      TEXT,
    duration_seconds INTEGER,
    outcome         TEXT,
    created_at      TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE INDEX IF NOT EXISTS idx_interactions_tenant ON interactions (tenant_id);
CREATE INDEX IF NOT EXISTS idx_interactions_call_id ON interactions (call_id);
CREATE INDEX IF NOT EXISTS idx_interactions_lead ON interactions (lead_id);
