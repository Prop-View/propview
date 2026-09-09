# PROP-102: LiveKit Media Server + SIP Gateway

Deploys the LiveKit WebRTC media server and SIP bridge that terminate the
Twilio trunk from PROP-101, and wires inbound calls into LiveKit rooms.
Also deploys Caddy (PROP-108) for TLS termination on the signaling
WebSocket — see "TLS (PROP-108)" below.

## Prerequisites

- A cloud VM (Linux) with a public, static IP.
- Inbound firewall rules open for:
  - `7880/tcp` — LiveKit signaling (WebRTC) — stays open for the plain `ws://` fallback described below, even once Caddy is deployed
  - `7881/tcp` — LiveKit TCP fallback
  - `50000-60000/udp` — LiveKit RTC media
  - `5060/udp` — SIP signaling (restrict to Twilio's SIP signaling IP ranges if possible)
  - `10000-20000/udp` — SIP RTP media
  - `80/tcp`, `443/tcp` — Caddy: ACME HTTP-01 challenge + `wss://` (PROP-108)
- A domain name with a DNS A record pointing at the VM's static IP (for PROP-108's TLS cert — optional; skip it and `wss://` just isn't available, everything else still works over `ws://`).
- Docker + Docker Compose installed on the VM.
- [LiveKit CLI (`lk`)](https://github.com/livekit/livekit-cli) installed locally or on the VM.

## Setup

```bash
cd infra/livekit
cp livekit.yaml.example livekit.yaml
cp sip-config.yaml.example sip-config.yaml
cp .env.example .env   # fill in LIVEKIT_DOMAIN once you have one -- see "TLS" below
```

Edit both `.yaml` files:
- Pick an `api_key` / `api_secret` pair (any random secret 32+ chars), same value in both files.
- Set `use_external_ip` targets to the VM's public IP (already `true` by default; LiveKit auto-detects it).

```bash
docker compose up -d
```

## TLS (PROP-108)

LiveKit's WebRTC media transport is already encrypted by default
(DTLS-SRTP — inherent to the protocol, nothing to configure). What's
*not* encrypted without this: the signaling WebSocket itself, served
plain (`ws://`) on `:7880`. `./Caddyfile` + the `caddy` service in
`docker-compose.yml` terminate real TLS in front of it — automatic
Let's Encrypt cert + renewal, `reverse_proxy` handles the WebSocket
upgrade transparently, no extra config needed.

This needs a real domain name with DNS pointing at the VM — the one
piece that can't be built or tested without an actual deployed VM (same
category of gap as PROP-101/102 themselves). Once `LIVEKIT_DOMAIN` is
set in `.env` and DNS resolves, `docker compose up -d` picks it up and
`wss://<your-domain>` replaces `ws://<vm-ip>:7880` everywhere (`main.py`'s
`LIVEKIT_URL`, `setup_sip_routing.sh`'s `LIVEKIT_URL`, etc. — the
`livekit` SDK/CLI accept either scheme transparently). Without a domain,
skip the `caddy` service (or leave `LIVEKIT_DOMAIN` unset and just don't
start it) and everything still works over plain `ws://`, exactly as it
did before PROP-108.

**Verification status:** `docker compose config` (with a placeholder
`LIVEKIT_DOMAIN`) resolves cleanly — the compose wiring itself is
correct. Not verified against a running Caddy binary or a real cert in
this environment (no Docker daemon available here, and no real domain to
request a Let's Encrypt cert for anyway) — that needs the actual
deployed VM, same gap as the rest of PROP-101/102.

Then wire the Twilio DID from PROP-101 to LiveKit rooms:

```bash
cp inbound-trunk.json inbound-trunk.local.json   # or edit in place
# replace REPLACE_WITH_TWILIO_DID with the number PROP-101 purchased

export LIVEKIT_URL=ws://<vm-public-ip>:7880
export LIVEKIT_API_KEY=<same as livekit.yaml>
export LIVEKIT_API_SECRET=<same as livekit.yaml>
./setup_sip_routing.sh
```

Finally, go back to PROP-101's `.env` and set:

```
LIVEKIT_SIP_ORIGINATION_URI=sip:<vm-public-ip>:5060
```

and re-run `provision_sip_trunk.py` (or update the trunk's Origination URL in
the Twilio console directly) so Twilio forwards inbound calls here.

## Definition of Done (from Sprint Plan)

- [ ] `livekit-server` and `livekit-sip` running on the cloud VM.
- [ ] Inbound trunk + dispatch rule created (`setup_sip_routing.sh`).
- [ ] Twilio trunk's Origination URL points at this VM's SIP address.
- [ ] Test call to the Twilio DID creates a `call-*` room in LiveKit
      (verify via `lk room list`).
- [ ] PROP-108 (TLS on WebSockets/WebRTC): Caddy config built
      (`./Caddyfile`, wired into `docker-compose.yml`, firewall rule added
      in `../gcp/provision_vm.sh`) — not yet exercised against a real
      cert/domain, same "blocked on a real deployed VM" gap as the rest of
      this checklist. WebRTC media itself is already encrypted
      (DTLS-SRTP) regardless, per `../observability/SECURITY_AUDIT.md`.
