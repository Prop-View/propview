#!/usr/bin/env bash
# Wires the Twilio DID (PROP-101) to LiveKit rooms via the LiveKit CLI.
# Run once, after livekit-server and livekit-sip are up.
#
# Requires: `lk` CLI (https://github.com/livekit/livekit-cli),
# LIVEKIT_URL / LIVEKIT_API_KEY / LIVEKIT_API_SECRET env vars set.

set -euo pipefail

: "${LIVEKIT_URL:?Set LIVEKIT_URL, e.g. ws://<vm-ip>:7880}"
: "${LIVEKIT_API_KEY:?Set LIVEKIT_API_KEY (must match livekit.yaml)}"
: "${LIVEKIT_API_SECRET:?Set LIVEKIT_API_SECRET (must match livekit.yaml)}"

script_dir="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

echo "Creating inbound SIP trunk..."
lk sip inbound-trunk create --config "$script_dir/inbound-trunk.json"

echo "Creating dispatch rule (one room per call, prefix 'call-')..."
lk sip dispatch-rule create --config "$script_dir/dispatch-rule.json"

echo "Done. Inbound calls to the Twilio DID now land in a LiveKit room named call-<id>."
