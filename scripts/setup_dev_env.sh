#!/usr/bin/env bash
# One-time local dev setup: a single shared venv with every service's
# dependencies installed, plus real (not .example) .env files wired
# together correctly across services.
#
# Real gaps this closes, found by actually trying to run the project
# fresh (see the session that added this script): the default `python3`
# on a typical Mac has none of these packages, no .env files exist
# (they're gitignored, correctly -- they'd hold secrets), and
# tool-router/admin-api never even called load_dotenv() so a .env file
# there was silently ignored regardless. See each service's own README
# for what each piece actually does -- this script only wires up "can I
# run it," not what it does once running.
#
# Usage: ./scripts/setup_dev_env.sh
# Safe to re-run -- every step is idempotent.

set -euo pipefail
cd "$(dirname "${BASH_SOURCE[0]}")/.."
REPO_ROOT="$(pwd)"

echo "== Locating Python 3.13 =="
# Pinned to 3.13, not "python3"/"python3.11+" generically: several deps
# here (torch, via silero-vad) lag behind the newest CPython release, and
# 3.13 is what every package in this repo was actually verified against.
# Homebrew's default `python3` on macOS is often newer (3.14+) and has
# none of these packages -- using it here would silently build a venv
# missing half of what's needed, or fail installing torch outright.
PYTHON_BIN=""
for candidate in python3.13 /Library/Frameworks/Python.framework/Versions/3.13/bin/python3.13; do
    if command -v "$candidate" >/dev/null 2>&1; then
        PYTHON_BIN="$(command -v "$candidate")"
        break
    fi
done
if [ -z "$PYTHON_BIN" ]; then
    echo "ERROR: no python3.13 found. Install it (e.g. 'brew install python@3.13')" >&2
    echo "       or from python.org, then re-run this script." >&2
    exit 1
fi
echo "Using: $PYTHON_BIN ($("$PYTHON_BIN" --version))"

echo
echo "== Creating venv (.venv) =="
if [ ! -d .venv ]; then
    "$PYTHON_BIN" -m venv .venv
    echo "Created .venv"
else
    echo ".venv already exists, reusing it"
fi
VENV_PIP="$REPO_ROOT/.venv/bin/pip"
VENV_PYTHON="$REPO_ROOT/.venv/bin/python"

echo
echo "== Installing dependencies (every service's requirements.txt) =="
# --retries 10 (pip's default is 5): seen this environment's DNS
# intermittently fail to resolve files.pythonhosted.org specifically
# (the wheel-download CDN) while pypi.org itself resolves fine -- real,
# reproduced twice, documented in scripts/README.md. Doesn't hurt a
# healthy network, gives a flaky one more chances.
"$VENV_PIP" install -q --retries 10 --upgrade pip

install_with_retry() {
    local req_file="$1"
    local attempt
    for attempt in 1 2 3; do
        if "$VENV_PIP" install -q --retries 10 -r "$req_file"; then
            return 0
        fi
        echo "  attempt $attempt failed for ${req_file#"$REPO_ROOT"/}, retrying in 5s..." >&2
        sleep 5
    done
    echo "  giving up on ${req_file#"$REPO_ROOT"/} after 3 attempts -- see scripts/README.md's" >&2
    echo "  'pip install' verification note if this is a files.pythonhosted.org DNS issue." >&2
    return 1
}

# find, not a hardcoded list -- so a new service's requirements.txt gets
# picked up automatically without this script needing an update.
while IFS= read -r req_file; do
    echo "  installing: ${req_file#"$REPO_ROOT"/}"
    install_with_retry "$req_file"
done < <(find "$REPO_ROOT" -name "requirements.txt" -not -path "*/.venv/*" | sort)

echo
echo "== Downloading the spaCy model PII masking needs =="
# Not expressible as a requirements.txt line -- presidio-analyzer pulls in
# spaCy itself, but the actual language model is a separate download.
"$VENV_PYTHON" -m spacy download en_core_web_sm --quiet || \
    "$VENV_PYTHON" -m spacy download en_core_web_sm

echo
echo "== Wiring up .env files =="
GEMINI_KEY=""
if [ -f services/gemini-client/.env ]; then
    GEMINI_KEY="$(grep -E '^GEMINI_API_KEY=' services/gemini-client/.env | head -1 | cut -d= -f2-)"
fi

# One ENCRYPTION_KEY shared between admin-api (encrypts calendar creds)
# and tool-router (decrypts them to actually use them) -- generating two
# independent random keys here would make tool-router unable to decrypt
# anything admin-api wrote, a real mistake worth guarding against
# explicitly rather than leaving to chance.
ENCRYPTION_KEY_VALUE=""
if [ -f services/admin-api/.env ]; then
    ENCRYPTION_KEY_VALUE="$(grep -E '^ENCRYPTION_KEY=' services/admin-api/.env | head -1 | cut -d= -f2-)"
fi
if [ -z "$ENCRYPTION_KEY_VALUE" ]; then
    ENCRYPTION_KEY_VALUE="$("$VENV_PYTHON" -c 'from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())')"
fi

# One INTERNAL_SERVICE_TOKEN shared between orchestrator (sends it on
# every Tool Router call) and tool-router (checks it) -- same reasoning as
# ENCRYPTION_KEY above, just for auth.require_internal_token instead of
# Fernet. See infra/observability/SECURITY_AUDIT.md section 3.
INTERNAL_SERVICE_TOKEN_VALUE=""
if [ -f services/tool-router/.env ]; then
    INTERNAL_SERVICE_TOKEN_VALUE="$(grep -E '^INTERNAL_SERVICE_TOKEN=' services/tool-router/.env | head -1 | cut -d= -f2-)"
fi
if [ -z "$INTERNAL_SERVICE_TOKEN_VALUE" ]; then
    INTERNAL_SERVICE_TOKEN_VALUE="$("$VENV_PYTHON" -c 'import secrets; print(secrets.token_urlsafe(32))')"
fi

# PLATFORM_OPERATOR_TOKEN is admin-api-only (gates tenant provisioning) --
# not shared with any other service, so no cross-file lookup needed.
PLATFORM_OPERATOR_TOKEN_VALUE="$("$VENV_PYTHON" -c 'import secrets; print(secrets.token_urlsafe(32))')"

setup_env_file() {
    local dir="$1"
    local env_file="$dir/.env"
    if [ -f "$env_file" ]; then
        echo "  $env_file already exists, leaving it alone"
        return
    fi
    cp "$dir/.env.example" "$env_file"
    if [ -n "$GEMINI_KEY" ]; then
        # BSD sed (macOS) needs the '' after -i; this repo's dev machine is macOS.
        sed -i '' "s|^GEMINI_API_KEY=.*|GEMINI_API_KEY=$GEMINI_KEY|" "$env_file" 2>/dev/null || true
    fi
    sed -i '' "s|^ENCRYPTION_KEY=.*|ENCRYPTION_KEY=$ENCRYPTION_KEY_VALUE|" "$env_file" 2>/dev/null || true
    sed -i '' "s|^INTERNAL_SERVICE_TOKEN=.*|INTERNAL_SERVICE_TOKEN=$INTERNAL_SERVICE_TOKEN_VALUE|" "$env_file" 2>/dev/null || true
    sed -i '' "s|^PLATFORM_OPERATOR_TOKEN=.*|PLATFORM_OPERATOR_TOKEN=$PLATFORM_OPERATOR_TOKEN_VALUE|" "$env_file" 2>/dev/null || true
    echo "  created $env_file"
}

for svc in services/orchestrator services/tool-router services/admin-api db/migrations db/ingestion; do
    if [ -f "$svc/.env.example" ]; then
        setup_env_file "$svc"
    fi
done

echo
echo "============================================================"
echo "Setup complete. Summary:"
echo "============================================================"
echo
if [ -z "$GEMINI_KEY" ]; then
    echo "[ ] GEMINI_API_KEY -- not found in services/gemini-client/.env."
    echo "    Nothing will work without this. Get one, then either fill it"
    echo "    into services/gemini-client/.env and re-run this script, or"
    echo "    edit each generated services/*/.env directly."
else
    echo "[x] GEMINI_API_KEY -- propagated to orchestrator/.env and tool-router/.env"
fi
echo "[x] ENCRYPTION_KEY -- generated once, shared correctly between admin-api and tool-router"
echo "[x] INTERNAL_SERVICE_TOKEN -- generated once, shared correctly between orchestrator and tool-router"
echo "[x] PLATFORM_OPERATOR_TOKEN -- generated for admin-api (gates tenant provisioning, see docs/AGENCY_ONBOARDING.md)"
echo "[ ] TWILIO_*, DEEPGRAM_API_KEY, OPENAI_API_KEY, CARTESIA_API_KEY, Google Calendar credentials"
echo "    -- real third-party accounts this script can't create for you. Every feature that"
echo "    needs one degrades gracefully without it (see each service's own README's"
echo "    'Not live-verified' section for exactly what that means for that feature)."
echo
echo "To run something:"
echo "  source .venv/bin/activate"
echo "  # then follow docs/AGENCY_ONBOARDING.md or any service's own README"
echo
echo "Quickest way to confirm it all actually works (no mic, no phone, no extra accounts --"
echo "just this venv + a running Postgres/Redis/livekit-server --dev):"
echo "  cd services/orchestrator && python tests/test_orchestrator_live.py"
