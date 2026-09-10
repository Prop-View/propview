# PROP-606: Security Audit & Secret Rotation

A real audit of this codebase's current state (not a template) — run
2026-09-08. Findings are graded by whether they're exploitable *as this
code actually runs today*, not by generic severity scores.

## 1. Secrets in source control — clean

Checked (not assumed):
- `git ls-files | grep '\.env$'` — no `.env` files ever tracked.
- `git log --all --diff-filter=A --name-only` for any historical `.env`
  commit — none.
- Regex scan across `*.py`/`*.js`/`*.ts`/`*.yaml`/`*.json` for
  `key/secret/password/token = "<16+ chars>"` patterns, excluding
  `.example` files and obvious local-dev placeholders
  (`devkey`/`devpassword`/`REPLACE_WITH_*`) — no matches.
- Scan for real-looking key formats (`sk-…`, `AIza…`, Twilio `AC[hex32]`,
  `ghp_…`, `ya29.…`) across all tracked files — no matches.
- `dump.rdb` (Redis dumps, could contain live session data) exist locally
  in two places but are `.gitignore`d and confirmed untracked.

**Result: no real secrets have ever been committed to this repo.**

## 2. Dependency vulnerabilities

Ran `pip-audit` against the actual installed environment, then filtered
to only packages this project's own `requirements.txt` files declare
(the raw scan flags 132 CVEs across 25 packages, but almost all of those
are unrelated packages present in this dev sandbox for other reasons —
noise, not this project's exposure).

**One real finding**: `cryptography` (used by `services/admin-api/crypto.py`
for Fernet-encrypted calendar credentials) was floored at `>=42.0.0`, and
the installed 48.0.1 carries known CVEs (PYSEC-2026-3552/3553/3554 —
X.509 certificate-chain verification bugs: wildcard SAN over-matching,
a recursive self-signed-chain DoS, and a PKCS7 padding oracle).

**Actual exploitability here: low.** This codebase only uses
`cryptography` for `Fernet` symmetric encrypt/decrypt — it never touches
the `x509` certificate-verification code path these CVEs are in. Bumped
the floor to `>=49.0.0` anyway (`services/admin-api/requirements.txt`,
`services/tool-router/requirements.txt`) as defense-in-depth, not because
an active exploit path was found.

**One real friction point found while fixing it**: `presidio-anonymizer`
(2.2.364) declares `cryptography<49.0.0` — installing `cryptography>=49`
produces a pip dependency-resolver warning. Tested anyway: all 10
`services/compliance/tests/test_pii_masking.py` cases still pass against
`cryptography==50.0.1` at runtime, so presidio's pin looks more
conservative than actually required — but this is worth re-checking
whenever presidio-anonymizer itself is upgraded, since a future presidio
release might genuinely need the older API.

## 3. No service-to-service authentication — fixed 2026-09-10

Originally the biggest real gap found by this audit: neither
`services/tool-router/main.py` nor `services/admin-api/main.py` had any
auth middleware, JWT validation, or API keys on any route — network
access to either service was equivalent to full access to every tenant's
data (RLS isolates tenants *from each other*, not unauthenticated callers
from tenants).

Implemented as this pass's own recommendation, not a rushed bolt-on:
- **tool-router** (`services/tool-router/auth.py`): a single shared
  secret (`INTERNAL_SERVICE_TOKEN`), since this service has exactly one
  legitimate caller class (the orchestrator).
- **admin-api** (`services/admin-api/auth.py`): per-tenant API keys, not
  a shared secret — admin-api is tenant-facing (one real caller per
  tenant), so a shared secret would let any tenant's caller act as any
  other tenant. A new `POST /admin/tenants/{tenant_id}/provision` route
  (gated by a separate `PLATFORM_OPERATOR_TOKEN`, held only by whoever
  operates the platform) mints a tenant's key and shows it exactly once;
  only its SHA-256 hash is ever stored
  (`db/migrations/006_admin_api_auth.sql`).

Both fail closed if their configured secret is unset (500, not silently
open). Live-verified end to end against real running instances, not just
unit tests: an unauthenticated `curl` gets a real 401 from both services;
the full provision → upload-listing → query-via-tool-router chain works
with real credentials; a tenant's key confirmed rejected against a
*different* tenant's routes (the actual point of per-tenant keys, not
just "auth exists somewhere"). See `services/tool-router/README.md`'s and
`services/admin-api/README.md`'s own "Auth" sections for the full detail
and exact test counts.

Not literally "JWT-based" as the plan's MVP Security Core section names —
bearer tokens checked with constant-time comparison achieve the same
threat-model outcome (no unauthenticated/cross-tenant access) without a
token-issuing/expiry/refresh apparatus this system doesn't otherwise
need; upgrading to real JWTs later wouldn't change the tenant-key model
above, only how the bearer token itself is validated.

## 4. No rate limiting anywhere — fixed 2026-09-10

Neither FastAPI service had request rate limiting. Now that §3 is fixed,
the threat this actually defends against isn't an unauthenticated flood
(rejected before touching Redis/Postgres at all) — it's a single
authenticated caller (a buggy or abusive tenant, or a leaked/misused
tenant API key) monopolizing shared infrastructure every other tenant's
traffic also depends on.

Implemented in both services, per tenant, via a Redis fixed-window
counter (`INCR`/`EXPIRE`) — not a sliding window or token bucket; simpler,
and its known failure mode (a caller can burst up to ~2x the limit right
at a window boundary) is a minor gap against the real threat model here
(sustained abuse, not one well-timed burst):

- `services/tool-router/rate_limit.py`: 120 requests / 10s per tenant on
  `/tools/call` (the tenant_id lives in the request body there, so this
  is enforced inline in the route handler, not a `Depends()`).
- `services/admin-api/rate_limit.py`: 30 requests / 60s per tenant across
  every tenant-scoped route (shared budget, not per-route — the point is
  bounding one tenant's *overall* traffic), with a separately, much
  tighter 5 requests / 60s budget just for `/provision` (mints/rotates a
  tenant's credential, a materially more sensitive action).

Both configurable via env vars (`RATE_LIMIT_*`, see each service's
`.env.example`) with the above as defaults. Live-verified against real
running instances, not just unit tests: 125 real HTTP calls to
tool-router in a tight loop returned exactly 120×200 then 5×429; 35 real
calls to admin-api returned exactly 29×200 then 6×429 (one request
already consumed by an earlier `/provision` call sharing the same
per-tenant budget) — the limits fire at exactly the configured
threshold, not approximately.

## 5. TLS (PROP-108) — config built, not yet deployed against a real cert

LiveKit's own WebRTC transport encrypts media by default (DTLS-SRTP) --
that part needed no work. The signaling WebSocket itself was plain
`ws://` with nothing in front of it; `../livekit/Caddyfile` +
`docker-compose.yml`'s new `caddy` service now TLS-terminate it
(automatic Let's Encrypt cert/renewal), and
`../gcp/provision_vm.sh` opens the firewall ports (80/443) it needs. See
`../livekit/README.md`'s "TLS (PROP-108)" section for the full picture.
Not yet exercised against a real cert/domain -- that needs an actual
deployed VM with a real domain pointed at it, the same category of gap
as PROP-101/102 themselves, not a new finding from this audit.

## 6. Encryption at rest — implemented correctly

`services/admin-api/crypto.py`'s Fernet encryption for
`tenant_settings.encrypted_calendar_credentials` is real (not a stub),
keyed by `ENCRYPTION_KEY`. This is the one piece of "encryption at rest"
the plan's MVP Security Core calls for that's actually built.

## 7. Secret rotation — design, not implemented

No HashiCorp Vault or AWS Secrets Manager integration exists — every
credential in this codebase (`GEMINI_API_KEY`, `TWILIO_*`,
`DEEPGRAM_API_KEY`, `OPENAI_API_KEY`, `CARTESIA_API_KEY`,
`ENCRYPTION_KEY`, `DATABASE_URL`) is a plain environment variable, read
once at process start via `os.environ.get(...)`. Rotating any of them
today means restarting every process that reads it.

**What real Vault/Secrets Manager integration would need** (not built —
requires a real Vault cluster or AWS account, same category of gap as
every other real-cloud-account dependency in this codebase):
- Replace `os.environ.get("X_API_KEY")` call sites with a fetch from the
  secrets backend (Vault's KV v2, or `boto3.client("secretsmanager")`),
  cached in-process with a TTL so rotation doesn't require a restart —
  every `os.environ.get(...)` call site across `services/*/main.py` and
  `.env.example` would need updating to this pattern.
- `ENCRYPTION_KEY` itself becomes the interesting case: rotating a
  Fernet key requires re-encrypting every existing
  `tenant_settings.encrypted_calendar_credentials` row with the new key
  before the old one can be retired — `crypto.py` would need a
  `rotate(old_key, new_key)` helper that decrypts with the old key and
  re-encrypts with the new one, run as a one-time migration per rotation.
- Twilio/Deepgram/OpenAI/Cartesia keys rotate independently at each
  provider's dashboard; the secrets-backend fetch above is what lets a
  rotated key propagate without a deploy.

## Definition of Done (from Sprint Plan)

- [x] Secret-in-source-control audit — clean, verified not assumed.
- [x] Dependency vulnerability scan — one real finding (cryptography),
      fixed; confirmed the rest is sandbox noise, not project exposure.
- [x] Documented the real gaps: no service-to-service auth, no rate
      limiting.
- [ ] HashiCorp Vault / AWS Secrets Manager actually stood up and wired
      in — needs a real cloud account, design documented above instead.
- [x] Service-to-service auth actually implemented — see section 3 above,
      no longer a follow-up.
- [x] Rate limiting actually implemented — see section 4 above, no
      longer a follow-up.
