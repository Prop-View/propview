# Local-only testing for PROP-102 (no cloud, no Twilio)

Validates the SIP → LiveKit room mechanism using a free SIP softphone on
your LAN instead of a real Twilio call. This does **not** prove Twilio can
reach you — RTP is UDP and needs a real public IP for that, which this
setup deliberately skips. It proves the LiveKit/SIP wiring itself works
before you spend anything on a VM.

## 1. Run LiveKit server natively (dev mode)

Docker Desktop on Mac doesn't support host networking, and dev mode is
simpler anyway:

```bash
brew install livekit
livekit-server --dev
```

This starts on `ws://localhost:7880` with default dev credentials
`devkey` / `secret`.

## 2. Run the SIP bridge in Docker

```bash
cd infra/livekit
cp sip-config.local.yaml.example sip-config.local.yaml
docker compose -f docker-compose.local.yml up -d
```

## 3. Find your Mac's LAN IP

```bash
ipconfig getifaddr en0
```

## 4. Wire up a local test trunk + dispatch rule

```bash
export LIVEKIT_URL=ws://localhost:7880
export LIVEKIT_API_KEY=devkey
export LIVEKIT_API_SECRET=secret

lk sip inbound-trunk create --config local-inbound-trunk.json
lk sip dispatch-rule create --config dispatch-rule.json
```

If either command errors on the exact field names, run
`lk sip inbound-trunk create --help` — the JSON schema has shifted between
LiveKit CLI versions; adjust to match what your installed `lk` expects.

## 5. Place a test call

Install a free SIP softphone (Linphone or Zoiper) on your phone or another
machine on the same Wi-Fi. Without registering an account, dial the raw SIP
URI:

```
sip:1000@<your-mac-lan-ip>:5060
```

(Linphone supports dialing a raw SIP address directly. If your softphone
insists on registering to an account first, Linphone is the easier of the
two for this.)

## 6. Verify

```bash
lk room list
```

A room named `call-*` appearing here means the SIP call was accepted and
routed into LiveKit — the exact mechanism that will handle real Twilio
calls once you deploy this to a VM with a public IP.

## Next step when ready for a real phone call

RTP needs a reachable public UDP endpoint — there's no way around that for
actual PSTN calls. When you're ready, the cheapest unblock is a small VPS
with a real public IP (DigitalOcean/Hetzner ~$4-6/mo) rather than GCP, or
skip self-hosting entirely with LiveKit Cloud's managed SIP trunking. Say
the word and I'll build out whichever path you pick.
