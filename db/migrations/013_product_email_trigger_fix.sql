-- The original shared email trigger referenced table-specific NEW fields
-- in a compound condition. PL/pgSQL evaluates those record fields even
-- when the table-name predicate is false, so appointment inserts failed.
-- Keep the table-specific fields inside their matching trigger branch.

CREATE OR REPLACE FUNCTION public.enqueue_product_emails()
RETURNS TRIGGER
LANGUAGE plpgsql
SET search_path = pg_catalog, public
AS $$
DECLARE
    recipient_email TEXT;
    lead_label TEXT;
BEGIN
    IF TG_TABLE_NAME = 'leads' THEN
        IF (TG_OP = 'INSERT' AND NEW.priority = 'high')
           OR (TG_OP = 'UPDATE' AND OLD.priority IS DISTINCT FROM NEW.priority
               AND NEW.priority = 'high') THEN
            lead_label := format('Lead %s', NEW.id);
            FOR recipient_email IN
                SELECT email FROM public.account_users
                WHERE tenant_id = NEW.tenant_id AND is_active AND email_verified_at IS NOT NULL
                  AND role = 'agent'
            LOOP
                INSERT INTO public.email_outbox (tenant_id, recipient, subject, body)
                VALUES (NEW.tenant_id, recipient_email, 'New high-priority Propview lead',
                        format('%s needs follow-up. Sign in to your agency dashboard to review the lead.', lead_label));
            END LOOP;
            IF NOT FOUND THEN
                FOR recipient_email IN
                    SELECT email FROM public.account_users
                    WHERE tenant_id = NEW.tenant_id AND is_active AND email_verified_at IS NOT NULL
                      AND role = 'owner'
                LOOP
                    INSERT INTO public.email_outbox (tenant_id, recipient, subject, body)
                    VALUES (NEW.tenant_id, recipient_email, 'New high-priority Propview lead',
                            format('%s needs follow-up. Sign in to your agency dashboard to review the lead.', lead_label));
                END LOOP;
            END IF;
        END IF;
    ELSIF TG_TABLE_NAME = 'appointments' AND TG_OP = 'INSERT' THEN
        IF NEW.status IN ('scheduled', 'confirmed') THEN
            FOR recipient_email IN
                SELECT email FROM public.account_users
                WHERE tenant_id = NEW.tenant_id AND is_active AND email_verified_at IS NOT NULL
                  AND role = 'agent' AND (NEW.agent_name IS NULL OR display_name = NEW.agent_name)
            LOOP
                INSERT INTO public.email_outbox (tenant_id, recipient, subject, body)
                VALUES (NEW.tenant_id, recipient_email, 'New Propview appointment',
                        format('Appointment %s is scheduled for %s. Sign in to your agency dashboard for details.',
                               NEW.id, NEW.scheduled_at));
            END LOOP;
            IF NOT FOUND THEN
                FOR recipient_email IN
                    SELECT email FROM public.account_users
                    WHERE tenant_id = NEW.tenant_id AND is_active AND email_verified_at IS NOT NULL
                      AND role = 'owner'
                LOOP
                    INSERT INTO public.email_outbox (tenant_id, recipient, subject, body)
                    VALUES (NEW.tenant_id, recipient_email, 'New Propview appointment',
                            format('Appointment %s is scheduled for %s. Sign in to your agency dashboard for details.',
                                   NEW.id, NEW.scheduled_at));
                END LOOP;
            END IF;
        END IF;
    END IF;
    RETURN NEW;
END;
$$;
