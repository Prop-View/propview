-- Closes the "no service-to-service authentication" gap flagged as the
-- biggest real finding in infra/observability/SECURITY_AUDIT.md section 3:
-- admin-api accepted every request from anyone who could reach the port,
-- with tenant_id taken directly from the request body -- meaning network
-- access to the service was equivalent to full access to every tenant's
-- data (RLS isolates tenants from each other, not unauthenticated callers
-- from tenants).
--
-- Per-tenant API key, hashed (never stored in plaintext) -- see
-- services/admin-api/auth.py. A 256-bit random key doesn't need slow
-- password hashing (bcrypt/scrypt/argon2, meant to resist brute-forcing a
-- low-entropy human password); a fast SHA-256 digest is the standard
-- approach for high-entropy API tokens (same pattern GitHub/Stripe use).

ALTER TABLE tenant_settings ADD COLUMN IF NOT EXISTS admin_api_key_hash TEXT;
