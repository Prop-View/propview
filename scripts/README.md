# Dev Setup Scripts

`setup_dev_env.sh` — one-time local setup: a single shared venv with
every service's dependencies installed, plus real `.env` files wired up
correctly across services (same `GEMINI_API_KEY` propagated everywhere
it's needed, the **same** `ENCRYPTION_KEY` shared between admin-api,
which encrypts calendar credentials, and tool-router, which decrypts
them — generating two independent random keys there would make
tool-router unable to decrypt anything admin-api wrote).

This exists because of a real gap found by actually trying to run the
project fresh: the default `python3` on a typical Mac has none of these
packages, no `.env` files exist (correctly gitignored — they'd hold
secrets), and — a real bug, not just "no docs" — `tool-router`'s,
`admin-api`'s, `db/migrations/apply_migrations.py`'s, and
`db/ingestion/ingest_listings.py`'s never called `load_dotenv()` at all,
so a `.env` file sitting right next to any of them was silently ignored
regardless. Fixed alongside this script (see the commits that added it).

```bash
./scripts/setup_dev_env.sh
```

Safe to re-run — every step is idempotent (won't overwrite an existing
`.env`, `pip install` is a no-op for already-satisfied requirements).

## Verification status

- **Python location + venv creation**: verified — the script correctly
  finds `python3.13` (pinned deliberately; see the script's own comment
  for why not whatever `python3` resolves to) and creates `.venv`.
- **`.env` wiring**: verified live, end-to-end, for all 5 locations —
  ran the actual file-generation logic, then: started real
  `tool-router`/`admin-api` processes off *only* the generated `.env`
  files (no explicit shell env vars) and confirmed both come up healthy
  and pass their own test suites, including a real Fernet encrypt
  (`admin-api`) / decrypt (`tool-router`) round trip using the one shared
  generated `ENCRYPTION_KEY`; ran `apply_migrations.py` off only its
  `.env` (correctly idempotent — skipped all 6 already-applied
  migrations); ran `ingest_listings.py` off only its `.env` and confirmed
  it correctly loaded `GEMINI_API_KEY`/`DATABASE_URL` and reached a real
  Gemini API call (which then hit the same network outage noted below,
  confirming the `.env` loading itself, not the network call, was what
  needed proving).
- **`pip install -r requirements.txt` for all 13 services, from a
  completely empty `.venv`**: **verified, full success**, 2026-09-09.
  Two earlier attempts hit a real, reproducible issue first —
  `files.pythonhosted.org` (the wheel-download CDN) intermittently
  failing DNS resolution in the verification sandbox while `pypi.org`
  itself resolved fine — which is why the script retries each
  `requirements.txt` install up to 3 times with a 5s pause (on top of
  pip's own `--retries 10` per attempt). The third attempt, with that
  retry logic in place, ran clean end to end: every one of the 13
  `requirements.txt` files installed (hitting and recovering from that
  same DNS flakiness once, on `services/scheduling`'s), the spaCy model
  downloaded, and all 5 `.env` files were generated correctly.
- **The resulting venv actually works**: ran
  `services/orchestrator/tests/` (38 tests, no mocked externals skipped)
  through `.venv/bin/python` directly — all 38 passed. Then ran
  `test_orchestrator_live.py` (real LiveKit server, real Redis, real
  Gemini API key, entirely through this fresh venv, no dependency on any
  Python environment set up any other way) — **PASS**: real participants
  joined a real room, real audio round-tripped through the resampling
  pipeline, session cleanup was verified correct. This is as close to
  "clone the repo, run one script, it works" as this environment could
  prove.
- **A real, second bug this whole exercise caught**: running every
  *other* service's test suite through this same fresh venv turned up
  one more gap -- `services/vap-sidecar/tests/` failed with
  `ModuleNotFoundError: No module named 'onnxruntime'`. `silero-vad`'s
  `onnx=True` mode needs `onnxruntime` at runtime, but neither
  `vap-sidecar/requirements.txt` nor `orchestrator/requirements.txt`
  (which also imports `vap_processor.py`) ever declared it -- it only
  ever worked before because *something else* had already pulled it into
  the shared global Python environment every earlier test run in this
  codebase's history used. A genuinely empty venv doesn't have that
  accident to lean on, which is exactly what caught this. Added
  `onnxruntime>=1.20.0` to both `requirements.txt` files; reran both the
  unit tests (4/4) and the real-LiveKit predictive-barge-in live test
  through the fresh venv afterward to confirm the fix, not just that the
  import succeeds in isolation.
