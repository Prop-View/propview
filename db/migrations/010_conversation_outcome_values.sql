-- Remove outcome values that have no implemented call-resolution rule.
-- Normalize any rows written under 009 before tightening the constraint.
UPDATE call_analytics
SET outcome = 'unknown'
WHERE outcome IN ('dropped', 'nurture');

ALTER TABLE call_analytics
    DROP CONSTRAINT IF EXISTS call_analytics_outcome_check;

ALTER TABLE call_analytics
    ADD CONSTRAINT call_analytics_outcome_check
    CHECK (outcome IN ('booked', 'qualified', 'transferred', 'unknown'));
