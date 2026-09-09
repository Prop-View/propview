#!/usr/bin/env bash
# PROP-102 infra: provisions the GCP Compute Engine VM that will run
# livekit-server + livekit-sip (see ../livekit/), with a static IP and
# the firewall rules LiveKit/SIP need.
#
# Prerequisites:
#   - gcloud SDK installed and authenticated: `gcloud auth login`
#   - A GCP project with billing enabled and the Compute Engine API on:
#       gcloud services enable compute.googleapis.com --project <id>
#
# Usage:
#   cp .env.example .env   # fill in GCP_PROJECT_ID at minimum
#   set -a; source .env; set +a
#   ./provision_vm.sh

set -euo pipefail

: "${GCP_PROJECT_ID:?Set GCP_PROJECT_ID (see .env.example)}"
GCP_ZONE="${GCP_ZONE:-us-central1-a}"
GCP_REGION="${GCP_REGION:-us-central1}"
VM_NAME="${VM_NAME:-propview-livekit-vm}"
MACHINE_TYPE="${MACHINE_TYPE:-e2-medium}"
IMAGE_FAMILY="${IMAGE_FAMILY:-ubuntu-2204-lts}"
IMAGE_PROJECT="${IMAGE_PROJECT:-ubuntu-os-cloud}"
IP_NAME="${VM_NAME}-ip"
FIREWALL_TAG="livekit-sip"
# Restricts the SIP signaling/RTP firewall rule to these source ranges
# (comma-separated CIDRs), e.g. Twilio's published SIP signaling IP ranges.
# Left unset, gcloud defaults to 0.0.0.0/0 (the whole internet) for a rule
# with no --source-ranges, which combined with infra/livekit/inbound-trunk.json's
# empty "allowed_addresses" leaves the SIP port open to unauthenticated
# inbound calls from anyone -- a toll-fraud / cost-abuse risk against the
# Gemini-backed agent behind it. Set this before running in anything but a
# throwaway/local test environment.
SIP_SOURCE_RANGES="${SIP_SOURCE_RANGES:-}"

script_dir="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

echo "Reserving static external IP ($IP_NAME)..."
gcloud compute addresses create "$IP_NAME" \
  --project "$GCP_PROJECT_ID" --region "$GCP_REGION" \
  || echo "  (already exists, reusing)"

STATIC_IP=$(gcloud compute addresses describe "$IP_NAME" \
  --project "$GCP_PROJECT_ID" --region "$GCP_REGION" --format="get(address)")
echo "Static IP: $STATIC_IP"

echo "Creating firewall rules for LiveKit + SIP..."
gcloud compute firewall-rules create "${FIREWALL_TAG}-tcp" \
  --project "$GCP_PROJECT_ID" \
  --allow tcp:7880,tcp:7881 \
  --target-tags "$FIREWALL_TAG" \
  --description "LiveKit signaling (PROP-102)" \
  || echo "  (already exists)"

gcloud compute firewall-rules create "${FIREWALL_TAG}-rtc-udp" \
  --project "$GCP_PROJECT_ID" \
  --allow udp:50000-60000 \
  --target-tags "$FIREWALL_TAG" \
  --description "LiveKit RTC media (PROP-102)" \
  || echo "  (already exists)"

gcloud compute firewall-rules create "${FIREWALL_TAG}-tls" \
  --project "$GCP_PROJECT_ID" \
  --allow tcp:80,tcp:443 \
  --target-tags "$FIREWALL_TAG" \
  --description "Caddy TLS termination for LiveKit signaling (PROP-108) -- 80 is ACME HTTP-01 challenge + redirect, 443 is wss://" \
  || echo "  (already exists)"

if [ -z "$SIP_SOURCE_RANGES" ]; then
  echo "WARNING: SIP_SOURCE_RANGES is not set -- the SIP/RTP firewall rule" >&2
  echo "  below will allow traffic from 0.0.0.0/0 (any IP on the internet)." >&2
  echo "  Set SIP_SOURCE_RANGES to Twilio's SIP signaling IP ranges (and set" >&2
  echo "  infra/livekit/inbound-trunk.json's allowed_addresses too) before" >&2
  echo "  using this outside a throwaway/local test environment." >&2
fi

gcloud compute firewall-rules create "${FIREWALL_TAG}-sip" \
  --project "$GCP_PROJECT_ID" \
  --allow udp:5060,udp:10000-20000 \
  --target-tags "$FIREWALL_TAG" \
  ${SIP_SOURCE_RANGES:+--source-ranges "$SIP_SOURCE_RANGES"} \
  --description "SIP signaling + RTP for the Twilio trunk (PROP-101/102)" \
  || echo "  (already exists)"

echo "Creating VM ($VM_NAME)..."
gcloud compute instances create "$VM_NAME" \
  --project "$GCP_PROJECT_ID" --zone "$GCP_ZONE" \
  --machine-type "$MACHINE_TYPE" \
  --image-family "$IMAGE_FAMILY" --image-project "$IMAGE_PROJECT" \
  --address "$STATIC_IP" \
  --tags "$FIREWALL_TAG" \
  --metadata-from-file startup-script="$script_dir/startup-script.sh"

cat <<EOF

Done.
  VM:        $VM_NAME ($GCP_ZONE)
  Static IP: $STATIC_IP

Next steps:
  1. SSH in once boot finishes (~1-2 min):
       gcloud compute ssh $VM_NAME --project $GCP_PROJECT_ID --zone $GCP_ZONE
  2. Copy infra/livekit/ onto the VM and run docker compose up -d there
     (see infra/livekit/README.md).
  3. Set LIVEKIT_SIP_ORIGINATION_URI=sip:$STATIC_IP:5060 in
     infra/telephony/provisioning/.env and re-run provision_sip_trunk.py
     (or update the Twilio trunk's Origination URL directly).
EOF
