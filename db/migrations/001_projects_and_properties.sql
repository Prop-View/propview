-- PROP-301: Core listings schema.
-- tenant_id is included now (default-scoped, no RLS yet) so PROP-601
-- (multi-tenant Row-Level Security, Sprint 6) only needs to add policies
-- on top of these columns rather than restructure the schema later.

CREATE TABLE IF NOT EXISTS projects (
    id            BIGSERIAL PRIMARY KEY,
    tenant_id     TEXT NOT NULL DEFAULT 'default',
    name          TEXT NOT NULL,
    developer     TEXT,
    city          TEXT NOT NULL,
    state         TEXT NOT NULL,
    description   TEXT,
    created_at    TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE TABLE IF NOT EXISTS properties (
    id              BIGSERIAL PRIMARY KEY,
    tenant_id       TEXT NOT NULL DEFAULT 'default',
    project_id      BIGINT REFERENCES projects(id) ON DELETE SET NULL,
    address         TEXT NOT NULL,
    city            TEXT NOT NULL,
    state           TEXT NOT NULL,
    zip_code        TEXT,
    property_type   TEXT NOT NULL,           -- house / condo / townhouse / land / ...
    status          TEXT NOT NULL DEFAULT 'active' CHECK (status IN ('active', 'pending', 'sold', 'off_market')),
    beds            SMALLINT,
    baths           NUMERIC(3,1),
    sqft            INTEGER,
    price           NUMERIC(12,2) NOT NULL,
    hoa_fee         NUMERIC(8,2),
    listing_agent   TEXT,
    amenities       JSONB NOT NULL DEFAULT '[]'::jsonb,
    floor_plan_url  TEXT,
    created_at      TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at      TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE INDEX IF NOT EXISTS idx_properties_tenant ON properties (tenant_id);
CREATE INDEX IF NOT EXISTS idx_properties_search ON properties (tenant_id, city, property_type, status, beds, price);
CREATE INDEX IF NOT EXISTS idx_properties_project ON properties (project_id);
