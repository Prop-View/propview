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
- **`pip install -r requirements.txt` for all 13 services**: every
  individual package in every `requirements.txt` in this repo was
  installed and used successfully earlier in this codebase's
  development — but a single clean end-to-end run of this script's
  install step specifically hit a network outage in the verification
  environment at the time (DNS resolution failing repeatedly, not a
  script bug — confirmed by `curl`/`nslookup` failing the same way
  independent of this script). Re-run `./scripts/setup_dev_env.sh` to
  complete that install once you have working network — the script
  itself is unchanged from what got this far successfully.
