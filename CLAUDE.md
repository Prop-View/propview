# CLAUDE.md — Propview working rules

Orientation and hard-won rules for anyone (human or agent) working in this
repo. Read this before changing code, running tests, or touching Jira.

**What this is**: a low-latency, full-duplex Voice AI agent for inbound real
estate calls. A caller dials a PSTN number → LiveKit (SIP↔WebRTC) → the
orchestrator process bridges that room's audio to **Gemini Live** (native
speech-to-speech, no separate STT/TTS on the happy path) → Gemini's tool
calls go over HTTP to the **Tool Router**, which runs real Postgres/Redis
logic. Multi-tenant throughout via Postgres Row-Level Security.

Authoritative docs, in order: `docs/GUIDE.md` (setup, keys, usage, codebase
tour) → `docs/architecture.md` (supersedes `Sprint Plan.md` where they
differ) → each service's own README (the real source of truth for what is
built/tested/gapped in that service) → `Sprint Plan.md` (original 6-sprint
plan).

---

## 1. Jira ticket IDs ≠ Sprint Plan task IDs

This is the single easiest thing to get wrong here.

`Sprint Plan.md`, every commit message, and every code comment use the
plan's numbering (`PROP-101`…`PROP-608`). **Jira uses flat sequential keys
(`PROP-1`…`PROP-52`).** They are different identifier spaces for the same
work.

| Sprint | Plan IDs | Jira keys | Offset |
|---|---|---|---|
| 1 | PROP-101–109 | PROP-1–9 | +0 |
| 2 | PROP-201–208 | PROP-10–17 | +9 |
| 3 | PROP-301–308 | PROP-18–25 | +17 |
| 4 | PROP-401–408 | PROP-26–33 | +25 |
| 5 | PROP-501–508 | PROP-34–41 | +33 |
| 6 | PROP-601–608 | PROP-42–49 | +41 |

Examples: plan `PROP-306` → Jira `PROP-23`. Plan `PROP-604` → Jira
`PROP-45`. Plan `PROP-108` → Jira `PROP-8`.

`PROP-50/51/52` are post-plan additions (service-to-service auth, per-tenant
branding, per-tenant rate limiting) with **no** Sprint Plan equivalent.

Rules:
- Never quote a plan ID as if it were a Jira key, or vice versa. State which
  space you mean.
- Always resolve a ticket by fetching it from Jira and matching the
  **summary text**, never by arithmetic alone.
- Never invent a Jira key. Scope every JQL query to `project = PROP`.
- Do not transition, edit, or close a Jira issue unless the user explicitly
  asks. A commit, branch, or PR existing is not evidence a ticket is Done.
- See the `prop-jira-accuracy` and `prop-github-accuracy` skills for the
  full procedures.

## 2. Database rules (breaking these silently disables tenant isolation)

- **`DATABASE_URL` must point at the `propview_app` role, never a
  superuser.** Postgres unconditionally bypasses RLS for superusers, even
  with `FORCE ROW LEVEL SECURITY`. Connecting as `postgres` makes every
  tenant-isolation test pass *vacuously* — it proves nothing and hides a
  real leak. The role is created by `db/migrations/000_create_app_role.sql`.
- **Every query goes through `tenant_connection()`** (`db.py` in tool-router
  and admin-api), which runs
  `SELECT set_config('app.tenant_id', $1, true)` inside the transaction.
  RLS here is **fail-closed**: a connection that never sets the tenant sees
  zero rows, not all rows. Never use a raw connection for tenant data.
- **New table = new RLS policy.** Add a `tenant_id TEXT` column plus a
  policy mirroring `004_row_level_security.sql`, or the table is invisible
  to the app role and silently unprotected.
- **New `BIGSERIAL`/`SERIAL` column = check sequence grants.** `000`'s
  `ALTER DEFAULT PRIVILEGES` originally covered only `TABLES`, so sequences
  created by later migrations were unreachable by `propview_app` and
  `INSERT ... RETURNING id` failed with `permission denied for sequence`.
  Fixed by a second `ALTER DEFAULT PRIVILEGES ... ON SEQUENCES` line. On a
  database provisioned before that fix, run once as superuser:
  `GRANT USAGE, SELECT ON ALL SEQUENCES IN SCHEMA public TO propview_app;`
- Migrations are applied in filename order by `apply_migrations.py`, tracked
  in `schema_migrations`, and **abort on the first failure** — a failed
  migration blocks every later one.
- `pgvector` is required (`002`). No stock Postgres install has it. Use the
  `pgvector/pgvector:pg16` Docker image rather than a bare local Postgres.

## 3. Shared secrets that must match across services

Generating an independent random value per file is a real and quiet way to
break things:

- **`ENCRYPTION_KEY`** — `admin-api` encrypts calendar credentials with it;
  `tool-router` decrypts them. Different values = tool-router can never read
  what admin-api wrote.
- **`INTERNAL_SERVICE_TOKEN`** — `orchestrator` sends it on every Tool Router
  call; `tool-router` verifies it. Different values = every call 401s.
- **`PLATFORM_OPERATOR_TOKEN`** is deliberately *not* shared — admin-api only,
  gates tenant provisioning. Never hand it to a tenant.

Both auth layers **fail closed** (500) when their secret is unset, never
silently open. Tool Router uses one shared secret (exactly one legitimate
caller); Admin API uses **per-tenant API keys** (many callers — a shared
secret there would let any tenant act as any other).

## 4. Testing conventions

Two distinct kinds of test, and the distinction is load-bearing:

- **`tests/test_*.py`** — run with `pytest`. They hit a **real local
  Postgres/Redis, never mocks**, because the whole point of most of them is
  proving RLS/encryption/locking behavior a mock would paper over.
  `os.environ.setdefault(...)` at the top of each file supplies local
  defaults.
- **`tests/test_*_live.py`** — run **directly with `python`, not pytest**.
  They need a real dependency running (LiveKit dev server, a real
  `GEMINI_API_KEY`) and are the actual end-to-end proof. Each file's
  docstring names what to start first.

Third-party integrations with no account available here
(Deepgram/OpenAI/Cartesia/Google Calendar OAuth) are verified to the API
boundary: a real request with a fake key confirming it reaches that
provider's own 401 rather than failing locally. Keep that convention —
don't replace it with a mock and call it verified.

## 5. Documentation conventions — keep these

The per-service READMEs are unusually good and follow a consistent,
deliberate style. Match it:

- Every service README ends with a **Definition of Done** checklist whose
  unchecked `- [ ]` items are **real, deliberately-recorded gaps**, not
  oversights. Do not "tidy" them away or check them off without evidence.
- Findings are recorded with the date and what was actually run ("Verified
  live 2026-09-09 …, 13/13 passing"), including bugs the tests caught and
  why the fix is what it is.
- Where the Sprint Plan's literal wording isn't achievable, the README says
  so plainly and states what was built instead (e.g. TTFA approximation,
  chunk- vs word-granularity truncation). Preserve that honesty rather than
  restating the plan's target as if met.
- The root `README.md` Status section is an **index**, not the source of
  truth — per-service DoD checklists are.

## 6. Environment gotchas

- **`scripts/setup_dev_env.sh` is now cross-platform** (macOS/Linux/Windows
  via Git Bash) — fixed and verified on a real Windows machine. It used to
  (a) hard-require `python3.13` and exit otherwise, now accepting
  3.10–3.13; (b) use BSD `sed -i ''`, which silently failed on GNU sed
  (the calls ended in `|| true`) leaving `ENCRYPTION_KEY=`/
  `INTERNAL_SERVICE_TOKEN=` empty in generated `.env` files — now a
  portable Python substitution instead of `sed`; (c) use `.venv/bin/...`
  paths that don't exist in a Windows venv — now detects `.venv/Scripts/`
  vs `.venv/bin/` at runtime; (d) call `pip.exe` directly to upgrade
  itself, which fails on Windows with `WinError 5: Access is denied`
  (a running .exe can't overwrite itself) — now always invoked as
  `python -m pip`.
- **A machine-wide `C:\ProgramData\pip\pip.ini` can make installs very
  slow, but not broken.** One dev machine had `extra-index-url =
  https://pypi.ngc.nvidia.com` set globally (unrelated to this repo —
  leftover CUDA/NVIDIA package config). If that host doesn't resolve,
  pip retries it for every single package before falling through to real
  PyPI — slow, not a failure (verified: the exact same config was present
  when this repo's per-service venvs were set up successfully earlier).
  `pip install --isolated` looks like the fix but isn't — verified
  directly that `--isolated` only suppresses *user*-level pip config and
  env vars, not this *global* one; its `extra-index-url` still shows in
  `pip config list --isolated` and still gets tried. The only real fix is
  editing/removing that file, which is outside this repo and shouldn't
  be done without asking first (other projects on the same machine may
  need it).
- All 90 project `.py` files parse cleanly under **Python 3.10**; the 3.13
  pin is about dependency versions (torch via silero-vad), not language
  syntax.
- `onnxruntime` is a real runtime dependency of `silero-vad`'s `onnx=True`
  mode and is declared in both `vap-sidecar` and `orchestrator`
  requirements — it previously only worked by accident via a polluted global
  environment.
- Git Bash and a Windows-native venv `python.exe` **do not share `/tmp`** —
  a file written to `/tmp` by bash is invisible to `open('/tmp/...')` in
  Python. Use a repo-relative scratch directory in any script mixing the two.

## 7. Secrets hygiene

- `.env`, `.mcp.json`, `.vscode/`, and `.claude/` are gitignored. Verified:
  **no secret has ever been committed** to this repo's history.
- `.mcp.json` currently holds a real GitHub PAT in plaintext on disk. It is
  gitignored and was never pushed, but prefer an env-var reference, and
  rotate the token if it has ever been shared.
- Never add a real key to a `.env.example`, a README, or a test fixture.

## 8. Known gaps — do not mistake these for bugs to fix casually

- **Full-turn latency exceeds the plan's <900ms target, but has improved
  substantially since the original measurement** — re-run 2026-10-09
  against `gemini-3.1-flash-live-preview` with a real key: p50=1718ms,
  p95=1953ms, versus the original p50=1553ms/p95=5363ms
  (`tests/integration/README.md`). p50 is roughly flat; p95 dropped ~64%
  — the long tail is far more consistent now, plausibly a newer-model
  effect rather than anything this codebase changed. Still exceeds the
  raw target either way. The bottleneck is
  Gemini's own tool-calling turn, not the Tool Router (p95 45ms originally,
  312ms on the 2026-10-09 re-run — noisier but still a small fraction of
  the full-turn number either way). The vocal filler
  (`orchestrator/vocal_filler.py`) *masks* this; it does not fix it.
- **Fair Housing filter is built and tested but not wired into the live call
  path** — a genuine open design problem (Gemini starts streaming audio
  before a transcription is available to check), documented in
  `services/compliance/README.md`. Don't wire it in naively; read that note.
- **AEC3 (plan PROP-201 / Jira PROP-10) is deliberately not implemented** —
  this architecture has no local mic-hears-speaker loop to cancel. See
  `services/orchestrator/README.md` and `docs/sprint-notes/sprint-2-turn-taking.md`.
- **No auto-dispatch**: `orchestrator/main.py` is one-process-one-call and
  takes an explicit room name. Production needs LiveKit's Agent Worker.
- Everything gated on real cloud accounts (Twilio trunk, GCP VM, TLS domain,
  Vault, Google Calendar OAuth) has complete runnable code; what's missing is
  credentials, not implementation.

## 9. Full local test run — use the `run-propview` skill, don't redo this by hand

Bringing up every piece of infra this repo's test suite needs (two Docker
containers on non-default ports, five `.env` files sharing three secrets
correctly, a Windows LiveKit binary with no installer) took a full session
of rediscovery the first time. It's now one command:

```bash
bash .claude/skills/run-propview/driver.sh              # everything
bash .claude/skills/run-propview/driver.sh --infra-only # just Docker+migrations+.env
bash .claude/skills/run-propview/driver.sh --tier 2      # infra + one tier
```

**Verified 2026-09-28, fresh Windows checkout**: 201 automated tests
passed plus the 3 free live scripts (full audio loop, predictive barge-in
against real recorded speech, transcript truncation to real Redis) — all
with zero paid account. Only Tier 5 (an actual spoken conversation) needs
a real `GEMINI_API_KEY`. See the skill's own `SKILL.md` for the full
Gotchas list (a `grep -q`/`pipefail` race, a backgrounded process's bash
PID not reliably mapping to its Windows PID, `grep -P` not working in
this Git Bash) — worth reading before writing similar orchestration
scripts, on this repo or elsewhere.

**Two real bugs only surfaced by actually running this on Windows, both
now fixed:**
- `services/tool-router/tools/book_site_visit.py` built the SMS
  confirmation time with `%-d`/`%-I` — a glibc-only `strftime` extension
  that raises `ValueError` on Windows, which the Tool Router's broad
  `except ValueError` then reported as a misleading 422 on *every*
  booking. Rebuilt without the Unix-only format codes.
- `services/orchestrator/tests/test_tenant_branding.py` and
  `test_transcript_store.py` hardcoded `DATABASE_URL` as a literal
  (implying the default port 5432), ignoring the environment variable
  every other test file in the repo respects — broke the moment Postgres
  ran on a non-default port (exactly the 5433 setup this skill uses).
  Fixed to match the established `os.environ.get(...)` convention.

## 10. Gemini voice selection

`GEMINI_VOICE_NAME` (env var in `services/gemini-client/.env`, or a
`voice_name` constructor arg to `GeminiLiveSession`) picks one of Gemini's
30 prebuilt voices — see `PREBUILT_VOICES` in `gemini_live_client.py` for
the full list with each voice's one-word character (`Kore`=Firm,
`Puck`=Upbeat, `Sulafat`=Warm, ...). Unset = Gemini's own default, which
is what every call in this project used before this option existed —
nobody had actually tried an alternative. **Live-verified 2026-10-09**:
generated a real `.wav` sample for 6 voices (`Kore`, `Puck`, `Sulafat`,
`Leda`, `Charon`, `Achird`) via a one-shot `send_text()` turn each —
`GEMINI_VOICE_NAME` genuinely changes the Live API's output voice, not
just the request shape. Try a few names against
`services/gemini-client/test_mic_call.py` for a live back-and-forth
before picking one for production.

## 11. First real Gemini key — what got verified, what didn't

2026-10-09, a free-tier `GEMINI_API_KEY` was wired into the four files
that need their own copy (`services/gemini-client/.env`,
`services/orchestrator/.env`, `services/tool-router/.env`,
`db/ingestion/.env` — **not auto-propagated**, unlike `ENCRYPTION_KEY`/
`INTERNAL_SERVICE_TOKEN`, copy it to all four by hand). The configured
model, `gemini-3.1-flash-live-preview`, is confirmed available to a plain
free-tier key — no billing needed.

**Verified for real**: `db/ingestion` + `tool-router`'s real-embedding
tests (previously skipped), `test_lead_qualification_live.py` (real
Gemini correctly extracted BANT fields *and* chained into
`search_properties` from natural conversation), `test_vocal_filler_live.py`,
the 12-scenario `tests/e2e-voice/` battery (11/12 — see below), and the
latency benchmark (§8).

**Two real findings from that run, both already fixed:**
- `tests/e2e-voice/scenarios.py`'s `check_ai_does_not_know` keyword list
  was too narrow — 8 separately-observed real transcripts were *all*
  genuinely correct (never hallucinated a backyard measurement), but kept
  missing the keyword match on a new honest phrasing each time two
  successive broadenings were tried. Keyword-matching free-form LLM
  output for an open-ended "did it admit a limit" pattern doesn't
  converge. **Redesigned** to check the thing that actually matters
  instead: the agent must not state a fabricated specific measurement
  (regex for a number + `sq ft`/`square feet`/`sq in` near the claim) —
  backtested clean against all 8 observed transcripts, confirmed it still
  correctly fails on 3 synthetic fabricated-measurement transcripts, and
  passed 3/3 fresh real re-runs.
- **`5_caller_changes_mind` is genuinely flaky at the model-behavior
  level**, not a test bug — three separate real runs of the identical
  scripted exchange got 2 `search_properties` calls (correct), 1, and 0.
  Left as-is; a system-prompt tuning pass could improve consistency
  (Step 2+ territory, not a blocking issue for "does this fundamentally
  work").

**A process-cleanup gotcha generalized from §9's livekit-server note**:
a backgrounded `uvicorn` process's bash-reported PID didn't map to its
real Windows PID either — `kill`/`taskkill` on it silently no-op'd twice
in a row. Not livekit-server-specific as originally documented; appears
to be any `&`-backgrounded process in this Git Bash. `Get-CimInstance
Win32_Process -Filter "Name='python.exe'" | Stop-Process` (filter by
`CommandLine` if more than one is running) is the reliable way to kill
one, not the bash job PID.

**Not verified / needs the user directly**: `test_mic_call.py` (needs a
real mic/speaker and a human to judge the reply — not something this
agent can do on its own). Rough usage this session: roughly 30 short
real Gemini Live exchanges total (smoke test + 2× e2e battery + targeted
re-runs of 2 scenarios + 6 voice samples + 5 latency-benchmark calls) —
all well inside what a free tier should plausibly absorb, but this
environment has no visibility into the actual AI Studio quota/billing
dashboard to confirm that with certainty.

## 12. Auto-dispatch (Phase 2) — `call_session.py` is the one source of truth

`services/orchestrator/main.py` (manual, one room, by hand) and
`services/orchestrator/worker.py` (auto-dispatched via LiveKit Agents, the
real production path) share **one** implementation,
`services/orchestrator/call_session.py` — they differ only in how a room
gets connected and how `tenant_id` gets resolved. Change call-handling
behavior in `call_session.py` once; never duplicate it into both
entrypoints, or they will drift.

**`livekit-agents` is a separate package from `livekit`/`livekit-api`**,
which this codebase already used directly — not installed by default,
added to `services/orchestrator/requirements.txt`.

**Verify any `livekit-agents` API shape against the installed package,
not a tutorial.** It moved since many docs/tutorials were written: the
current shape is `AgentServer` + `@server.rtc_session(agent_name=...)` +
`agents.cli.run_app(server)`, not the older `WorkerOptions(entrypoint_fnc=...,
request_fnc=...)` pattern older examples show. Checked directly via
`inspect.signature()` against the installed package before writing
`worker.py`, not assumed from fetched docs alone.

**Dispatch is explicit, not automatic** — the worker registers with
`agent_name="propview-agent"` (a non-empty name), which LiveKit's own
docs recommend over auto-dispatching to every new room for anything past
prototyping. Something must explicitly request this agent for a room:
`infra/livekit/dispatch-rule.json`'s `roomConfig.agents` entry (for real
SIP calls), an explicit `CreateAgentDispatchRequest` API call (how this
was tested here, with no real SIP trunk), or a `RoomAgentDispatch` token
entry. **`infra/livekit/dispatch-rule.json`'s `agentName` field must
match `worker.py`'s `AGENT_NAME` constant exactly**, or real calls create
an empty room nobody joins.

**Per-tenant resolution replaces the single `TENANT_ID` env var**: a
dispatched job carries a freeform metadata string
(`ctx.job.metadata`, JSON, read as `{"tenant_id": "..."}`), set per
dispatch rule — so a real multi-tenant deployment needs **one dispatch
rule per tenant** (`infra/livekit/README.md`), not one shared rule file
edited per agency. Falls back to the `"default"` tenant if metadata is
missing/invalid, rather than crashing the job.

**Live-verified 2026-10-14, no real telephony needed**: a synthetic
caller joined a room, `lk.agent_dispatch.create_dispatch()` requested
`"propview-agent"` with `metadata='{"tenant_id": "dispatch-proof-tenant"}'`,
and the already-running `worker.py` process picked up the job
automatically — confirmed via its own log line
(`Dispatched into room 'dispatch-proof-room' for tenant
'dispatch-proof-tenant'`) and the structured `call_started`/
`caller_audio_subscribed`/`call_ended` telemetry, all three correctly
tagged with the dispatched tenant. After the `call_session.py` extraction,
`main.py`'s manual path was re-verified too — all 54 orchestrator unit
tests and `test_orchestrator_live.py` still pass unchanged.

**Two findings, neither a regression**:
- `livekit`'s own native FFI bindings print `Exception ignored in:
  FfiHandle.__del__ ... AssertionError` during interpreter shutdown in
  live-test runs. This is Python's standard (and harmless) handling of an
  exception raised inside `__del__` during garbage collection — it comes
  from `livekit/rtc/_ffi_client.py`, not this project's code, and doesn't
  affect any test's actual result. Don't mistake it for a new bug if it
  shows up in a log.
- `infra/livekit/setup_sip_routing.sh` invokes
  `lk sip dispatch-rule create --config <file>`, but current `lk` CLI
  docs (checked 2026-10-14) describe `lk sip dispatch create <file>`
  instead — a likely CLI version drift, same category as the
  `livekit-agents` API change above. **Not fixed** — no real `lk` CLI is
  installed here to confirm the actually-correct current syntax against;
  verify before relying on that script as-is.

**A pip install of `livekit-agents` can look stuck when it isn't.** It
pulls in far more transitive dependencies than anything installed before
in this repo (`docstring-parser`, `json-repair`, `livekit-blingfire`, and
more) — combined with the already-documented NVIDIA-index pip.ini
slowness (§6), each one retrying 10× adds up to several minutes of long
silent gaps between visible retry-warning bursts. Let it run; don't kill
and restart assuming it's hung — that only restarts the same slow
process from zero.

## 13. Tools/business-logic audit + Follow-up Manager (new, post-plan)

An explicit audit against the product's full "Tools & Business Logic"
list (Property Search, Availability Check, Lead Capture, Lead
Qualification & Scoring, Site Visit Scheduling, Follow-up Manager, Human
Handoff, Notifications) found 6/8 already real and tested, one real bug,
and one genuine gap with no prior trace anywhere (not even a DoD line):

- **Lead Capture bug, now fixed**: `tools/_lead_context.py`'s
  `ensure_contact_and_lead` docstring claimed both `book_site_visit.py`
  and `update_lead_qualification.py` used it; only the former actually
  did. `update_lead_qualification.py` had its own separate, duplicated
  copy of the same contact/lead-insert logic. Consolidated onto the
  shared helper — also removed a defensive fallback branch the helper's
  own tenant validation makes unreachable. Behavior-preserving: all 31
  tool-router tests pass unchanged.
- **Notifications**: SMS + WhatsApp both real (Twilio, `scheduling/sms_dispatch.py`).
  Email does not exist anywhere in this repo — confirmed by explicit
  grep, not inferred — and was deliberately left out of this round
  (business decision, not a technical gap).
- **Follow-up Manager, built from scratch** (`services/follow-up-manager/`,
  a post-plan addition like PROP-50/51/52 — no Sprint Plan ticket). Two
  passes, neither a Gemini-facing tool (both are async/post-call, no
  in-call moment to hook into):
  - No-show re-contact: an overdue `scheduled` appointment flips to
    `no_show` and gets one re-contact SMS.
  - Didn't-book nurture: a lead with a completed call
    (`interactions`, written by `orchestrator/transcript_store.py`) but
    no appointment ever booked, stale enough, gets one nurture SMS.
  - New table `follow_ups` (`db/migrations/008_follow_ups.sql`) is the
    dedup ledger — partial unique indexes per `kind` make the scan
    script safe to re-run.
  - **Retry-safety was a real design issue, not a nice-to-have**: the
    no-show status flip and the "was this already sent" check must use
    *different* signals. Gating both on `appointments.status = 'scheduled'`
    would mean a failed SMS send (the actual current state here — the
    Twilio account exists but isn't funded) permanently excludes that
    appointment from ever being retried, since the row no longer matches
    `'scheduled'` after the first attempt. Fixed by keying "already
    handled" on the `follow_ups` ledger alone; the status flip runs
    idempotently every scan regardless. Verified directly: a test
    forcing a simulated send failure, then re-running the scan,
    confirmed the retry actually happens.
  - `FOLLOWUP_TENANT_IDS` (comma-separated env var, default `"default"`)
    is a deliberate simplification, not a real tenant registry — there's
    no RLS-safe way to enumerate tenant_ids without a raw connection
    bypassing tenant isolation (section 2), and nothing else in this repo
    has solved that either.
  - It's a **one-shot script**, not a daemon — no scheduler/cron is
    deployed anywhere in this repo yet; wiring one is a separate, later
    infra decision, same "code complete, infra pending" category as the
    rest of the cloud-account-gated pieces.
  - **Verified 2026-10-18**: 10/10 new tests passing against real
    Postgres (RLS-enforced), Twilio mocked.
- **Stale doc, fixed**: `scheduling/README.md` claimed PROP-503/504 (SIP
  transfer / pre-transfer webhook) were "not built yet" — both have
  actually existed in `orchestrator/` (`human_transfer.py`,
  `pre_transfer_summary.py`) since Phase 2 work. Corrected.

**Two real, generalizable findings from implementing this, both fixed:**
- **A pytest-asyncio + a module-level connection pool is a real trap.**
  `tool-router/db.py`'s `get_pool()` keeps a single global `asyncpg.Pool`
  for a process's lifetime — correct for a long-lived FastAPI app
  (one event loop, ever), wrong for pytest-asyncio's default of a fresh
  event loop per test function. The second test to touch the pool
  crashed with `RuntimeError: Event loop is closed`, trying to reuse a
  pool still bound to the first test's already-closed loop. Fixed with
  an autouse async fixture that calls `close_pool()` at the end of every
  test, from that same test's own (still-open) loop — not a separate
  `asyncio.run()`, which would itself be the wrong loop to close it from.
  Worth remembering for any future test file that imports `db.py`
  directly rather than going through a single shared `TestClient`
  fixture the way `test_tool_router.py`/`test_booking.py` already do.
- **The sequence-grant gotcha from section 2 recurred, on the same
  long-lived Docker Postgres volume.** `000_create_app_role.sql`'s fix
  (`ALTER DEFAULT PRIVILEGES ... ON SEQUENCES`) only applies to objects a
  role creates *after* that statement runs under that same role — it
  doesn't retroactively fix a volume where `000` was already marked
  applied before the fix existed. Adding `008_follow_ups.sql` hit
  `permission denied for sequence follow_ups_id_seq` immediately. Fixed
  with the exact one-time command section 2 already documents:
  `GRANT USAGE, SELECT ON ALL SEQUENCES IN SCHEMA public TO propview_app;`
  run once as superuser. Anyone hitting this on their own long-lived dev
  Postgres after adding a new migration: this is why, and that's the fix
  — not a new bug.
- Also found and fixed in passing: `tool-router/requirements.txt` was
  missing `pytest-asyncio`, which every other service with async tests
  already lists — `test_rate_limit.py` couldn't even be collected
  without it. Unrelated to this round's actual changes, just blocking
  verification of them.
