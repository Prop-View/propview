-- Dedup ledger for services/follow-up-manager/followup_scan.py: one row
-- per follow-up actually sent, so a re-run of the scan (it's a one-shot
-- script, meant to be invoked repeatedly on a schedule -- see that
-- service's README) never sends the same no-show re-contact or nurture
-- touch twice for the same appointment/lead.

CREATE TABLE IF NOT EXISTS follow_ups (
    id              BIGSERIAL PRIMARY KEY,
    tenant_id       TEXT NOT NULL DEFAULT 'default',
    lead_id         BIGINT NOT NULL REFERENCES leads(id) ON DELETE CASCADE,
    appointment_id  BIGINT REFERENCES appointments(id) ON DELETE CASCADE,
    kind            TEXT NOT NULL CHECK (kind IN ('no_show', 'nurture')),
    sent_at         TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE INDEX IF NOT EXISTS idx_follow_ups_tenant ON follow_ups (tenant_id);

-- One no-show follow-up per appointment; appointment_id is NULL for the
-- nurture kind (it isn't tied to any one appointment), so this constraint
-- only bites where it's meaningful.
CREATE UNIQUE INDEX IF NOT EXISTS idx_follow_ups_no_show_once
    ON follow_ups (appointment_id)
    WHERE kind = 'no_show';

-- One nurture follow-up per lead -- a lead that calls back in and
-- qualifies further moves out of the scan's nurture candidate set
-- entirely (see followup_scan.py's query), so this never needs a second
-- nurture row for the same lead.
CREATE UNIQUE INDEX IF NOT EXISTS idx_follow_ups_nurture_once
    ON follow_ups (lead_id)
    WHERE kind = 'nurture';

ALTER TABLE follow_ups ENABLE ROW LEVEL SECURITY;
ALTER TABLE follow_ups FORCE ROW LEVEL SECURITY;
DROP POLICY IF EXISTS tenant_isolation ON follow_ups;
CREATE POLICY tenant_isolation ON follow_ups
    USING (tenant_id = current_setting('app.tenant_id', true))
    WITH CHECK (tenant_id = current_setting('app.tenant_id', true));
