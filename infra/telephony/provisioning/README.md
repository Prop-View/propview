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

## Pre-funding verification (2026-10-14)

Before running `provision_sip_trunk.py` against a real (but not yet
funded) Twilio trial account, three read-only checks confirmed what's
safe to do now vs. what needs funding first:

- **Account auth**: credentials are valid — `client.api.accounts(sid).fetch()`
  returned `status='active'`, `type='Trial'`.
- **Elastic SIP Trunking is hard-blocked on a trial account** —
  `client.trunking.v1.trunks.list()` returned a real Twilio 401
  (`code=20003`, "This feature is not available on a Trial account.
  Please upgrade your account to gain access."). This is a genuine
  Twilio account-tier restriction, not a bug or a credentials problem —
  `provision_sip_trunk.py` cannot succeed past step 1 until the account
  is funded, no matter how the script is invoked.
- **The default `TWILIO_NUMBER_AREA_CODE=512` currently has zero
  available local numbers in Twilio's inventory** —
  `available_phone_numbers("US").local.list(area_code="512", ...)`
  returns 0 results, with and without `voice_enabled`. This is
  independent of the trial restriction: an unfiltered US local search
  (no area code) returns real numbers fine, so the search API itself
  works — 512 specifically is depleted in Twilio's current stock (a
  known real-world quirk of that area code; Austin's actual overlay
  code `737` is the practical substitute). Re-check at purchase time —
  pick `737`, or drop the area-code filter, if `512` is still empty.

Buying the number (`incoming_phone_numbers.create()`) was deliberately
**not** attempted here, even though trial accounts can typically claim
one free number — doing so before the trunk-creation step is unblocked
would risk the exact orphaned-number failure mode `provision_sip_trunk.py`
already warns about (a purchased, billed number with no trunk able to
attach to it on a trial account). Wait for funding, then run the full
script in one pass.
