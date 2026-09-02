# PROP-101: SIP Trunk & DID Provisioning

Provisions the Twilio Elastic SIP Trunk and inbound phone number that Sprint 1's
voice loop depends on.

## Setup

```bash
cd infra/telephony/provisioning
python3 -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt
cp .env.example .env
# fill in TWILIO_ACCOUNT_SID / TWILIO_AUTH_TOKEN from the Twilio console,
# and pick a NUMBER_AREA_CODE
python provision_sip_trunk.py
```

## What it does

1. Buys a voice-enabled local DID in the configured area code.
2. Creates an Elastic SIP Trunk (`TWILIO_TRUNK_FRIENDLY_NAME`).
3. Points the trunk's Origination URL at `LIVEKIT_SIP_ORIGINATION_URI` — the
   LiveKit SIP gateway that PROP-102 stands up. If PROP-102 isn't done yet,
   leave it as the placeholder; re-run (or set it via the Twilio console)
   once the gateway has a real address.
4. Attaches the purchased number to the trunk.

## Definition of Done (from Sprint Plan)

- [ ] Twilio (or Telnyx) SIP trunk exists with a real DID attached.
- [ ] Trunk SID + phone number recorded for PROP-102 to consume.
- [ ] Once PROP-102 is live, a test inbound call to the DID reaches the
      LiveKit SIP gateway.
