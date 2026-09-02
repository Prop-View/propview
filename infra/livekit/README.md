# PROP-102: LiveKit Media Server + SIP Gateway

Deploys the LiveKit WebRTC media server and SIP bridge that terminate the
Twilio trunk from PROP-101, and wires inbound calls into LiveKit rooms.

## Prerequisites

- A cloud VM (Linux) with a public, static IP.
- Inbound firewall rules open for:
  - `7880/tcp` — LiveKit signaling (WebRTC)
  - `7881/tcp` — LiveKit TCP fallback
  - `50000-60000/udp` — LiveKit RTC media
  - `5060/udp` — SIP signaling (restrict to Twilio's SIP signaling IP ranges if possible)
  - `10000-20000/udp` — SIP RTP media
- Docker + Docker Compose installed on the VM.
- [LiveKit CLI (`lk`)](https://github.com/livekit/livekit-cli) installed locally or on the VM.

## Setup

```bash
cd infra/livekit
cp livekit.yaml.example livekit.yaml
cp sip-config.yaml.example sip-config.yaml
```

Edit both files:
- Pick an `api_key` / `api_secret` pair (any random secret 32+ chars), same value in both files.
- Set `use_external_ip` targets to the VM's public IP (already `true` by default; LiveKit auto-detects it).

```bash
docker compose up -d
```

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
