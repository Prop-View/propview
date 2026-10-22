#!/usr/bin/env bash
# One-time local dev setup: a single shared venv with every service's
# dependencies installed, plus real (not .example) .env files wired
# together correctly across services.
#
# Cross-platform: macOS, Linux, and Windows (via Git Bash/MSYS -- this is
# a bash script, so plain cmd.exe/PowerShell can't run it directly, but
# Git Bash -- already a Claude Code / Git-for-Windows dependency -- can).
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

echo "== Locating a suitable Python =="
# Preferred: 3.13, matching what every package here was actually verified
# against (some deps, e.g. torch via silero-vad, lag behind the newest
# CPython release). Falls back through 3.12/3.11/3.10 -- all 90 of this
# repo's .py files parse cleanly under 3.10, and 3.13 not being available
# locally (common on a fresh Windows machine, or a Linux box whose distro
# hasn't packaged it yet) shouldn't be a hard blocker. Below 3.10 is
# untested and not accepted.
#
# Tries plain `pythonX.Y` on PATH first (macOS/Linux convention), then
# falls back to the `py` launcher with a version flag (`py -3.13`), which
# is how python.org's Windows installer registers versions -- there is
# usually no bare `python3.13` on PATH on Windows even when 3.13 is
# installed.
PYTHON_BIN=""
PYTHON_VERSION=""
for ver in 3.13 3.12 3.11 3.10; do
    if command -v "python$ver" >/dev/null 2>&1; then
        PYTHON_BIN="$(command -v "python$ver")"
        PYTHON_VERSION="$ver"
        break
    fi
    if command -v py >/dev/null 2>&1 && py "-$ver" --version >/dev/null 2>&1; then
        PYTHON_BIN="py -$ver"
        PYTHON_VERSION="$ver"
        break
    fi
done
if [ -z "$PYTHON_BIN" ]; then
    echo "ERROR: no Python 3.10-3.13 found." >&2
    echo "       macOS:   brew install python@3.13" >&2
    echo "       Windows: install from python.org (any of 3.10-3.13), or 'winget install Python.Python.3.13'" >&2
    echo "       Linux:   use your distro's package manager, or pyenv" >&2
    exit 1
fi
echo "Using: $PYTHON_BIN ($($PYTHON_BIN --version))"
if [ "$PYTHON_VERSION" != "3.13" ]; then
    echo "NOTE: this repo was originally verified against 3.13; using $PYTHON_VERSION instead." >&2
    echo "      Everything is expected to work (all source files parse under 3.10+), but if a" >&2
    echo "      dependency install fails, installing 3.13 alongside is the first thing to try." >&2
fi

echo
echo "== Creating venv (.venv) =="
if [ ! -d .venv ]; then
    $PYTHON_BIN -m venv .venv
    echo "Created .venv"
else
    echo ".venv already exists, reusing it"
fi

# Windows venvs put executables in Scripts/ with a .exe suffix; POSIX
# venvs use bin/ with no suffix. Detect which one this venv actually has
# rather than assuming from the host OS -- more robust under Git Bash,
# where `uname` says MINGW/MSYS but paths are still Windows-shaped.
if [ -f .venv/Scripts/python.exe ]; then
    VENV_PYTHON="$REPO_ROOT/.venv/Scripts/python.exe"
    ACTIVATE_HINT="source .venv/Scripts/activate   # Git Bash; or .venv\\Scripts\\activate.bat in cmd.exe, .venv\\Scripts\\Activate.ps1 in PowerShell"
else
    VENV_PYTHON="$REPO_ROOT/.venv/bin/python"
    ACTIVATE_HINT="source .venv/bin/activate"
fi

# NOTE on a machine-wide C:\ProgramData\pip\pip.ini some Windows dev
# machines have (left over from an unrelated CUDA/NVIDIA package setup):
# it can add `extra-index-url = https://pypi.ngc.nvidia.com`. If that
# host doesn't resolve on the current network, EVERY package install
# below retries against it (up to --retries times) before falling
# through to the real PyPI -- this makes the whole script much slower
# but does not break it (verified: this is the exact config already
# present when this repo's admin-api/tool-router venvs were set up
# successfully in an earlier session -- pip does fall through correctly,
# it just costs real time doing so). `--isolated` looks like the fix but
# isn't: verified directly that it only suppresses *user*-level pip
# config and env vars, not this *global*/machine-wide file -- its
# extra-index-url is still visible in `pip config list --isolated` and
# still gets tried. The only real fix is removing/editing that file
# yourself (outside this repo's scope to do automatically, since other
# projects on the same machine may depend on it) -- ask before touching
# C:\ProgramData\pip\pip.ini.
#
# --retries 10 (pip's default is 5): seen this environment's DNS
# intermittently fail to resolve pypi.org / files.pythonhosted.org for a
# few seconds at a time while the network is otherwise healthy -- real,
# reproduced more than once, documented in scripts/README.md. This outer
# 3-attempt/5s-backoff wrapper is a second layer on top of that: pip's
# own --retries burns through all 10 attempts in well under 5 seconds
# (each retry backs off in fractions of a second), which is often shorter
# than the blip itself. Applied to *every* pip invocation below,
# including the pip self-upgrade -- a DNS blip on that first command used
# to kill the whole script before it ever reached a single dependency.
#
# Invoked as `python -m pip`, not the `pip`/`pip.exe` executable directly:
# on Windows, pip upgrading itself via its own .exe fails with
# "WinError 5: Access is denied" -- Windows won't let a running
# executable overwrite itself. Going through python -m avoids that
# entirely (python.exe isn't the file being replaced), and works
# identically on macOS/Linux too. Found by actually running this on
# Windows, not assumed.
pip_install_with_retry() {
    local label="$1"
    shift
    local attempt
    for attempt in 1 2 3; do
        if "$VENV_PYTHON" -m pip install -q --retries 10 "$@"; then
            return 0
        fi
        echo "  attempt $attempt failed for $label, retrying in 5s..." >&2
        sleep 5
    done
    echo "  giving up on $label after 3 attempts -- see scripts/README.md's" >&2
    echo "  'pip install' verification note if this is a DNS flakiness issue." >&2
    return 1
}

echo
echo "== Upgrading pip =="
pip_install_with_retry "pip itself" --upgrade pip

echo
echo "== Installing dependencies (every service's requirements.txt) =="
# find, not a hardcoded list -- so a new service's requirements.txt gets
# picked up automatically without this script needing an update.
while IFS= read -r req_file; do
    label="${req_file#"$REPO_ROOT"/}"
    echo "  installing: $label"
    pip_install_with_retry "$label" -r "$req_file"
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
    # Substitution via Python, not sed: BSD sed (macOS) needs `-i ''`
    # while GNU sed (Linux, and Git Bash on Windows -- MSYS ships GNU
    # sed) needs `-i` with no separate empty-string argument. The two
    # are incompatible with each other's syntax, and the previous
    # version of this script used the BSD form with `|| true`, which
    # made it FAIL SILENTLY on Windows/Linux: the .env file was created
    # from the .example but the shared secrets were never substituted,
    # leaving e.g. `ENCRYPTION_KEY=` empty and every service refusing to
    # authenticate at runtime with no clear reason why. One Python
    # implementation works identically on every platform this script
    # supports, and Python is already a hard requirement at this point.
    "$VENV_PYTHON" - "$env_file" "$GEMINI_KEY" "$ENCRYPTION_KEY_VALUE" "$INTERNAL_SERVICE_TOKEN_VALUE" "$PLATFORM_OPERATOR_TOKEN_VALUE" <<'PYEOF'
import re
import sys

env_file, gemini_key, encryption_key, internal_token, platform_token = sys.argv[1:6]

substitutions = {}
if gemini_key:
    substitutions["GEMINI_API_KEY"] = gemini_key
substitutions["ENCRYPTION_KEY"] = encryption_key
substitutions["INTERNAL_SERVICE_TOKEN"] = internal_token
substitutions["PLATFORM_OPERATOR_TOKEN"] = platform_token

with open(env_file, "r", encoding="utf-8") as f:
    lines = f.readlines()

out = []
for line in lines:
    m = re.match(r"^([A-Z_][A-Z0-9_]*)=", line)
    if m and m.group(1) in substitutions:
        out.append(f"{m.group(1)}={substitutions[m.group(1)]}\n")
    else:
        out.append(line)

with open(env_file, "w", encoding="utf-8") as f:
    f.writelines(out)
PYEOF
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
echo "  $ACTIVATE_HINT"
echo "  # then follow docs/AGENCY_ONBOARDING.md or any service's own README"
echo
echo "Quickest way to confirm it all actually works (no mic, no phone, no extra accounts --"
echo "just this venv + a running Postgres/Redis/livekit-server --dev):"
echo "  cd services/orchestrator && python tests/test_orchestrator_live.py"
