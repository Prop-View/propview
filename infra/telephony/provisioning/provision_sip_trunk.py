"""
PROP-101: Provision Twilio SIP trunk and DID number.

Buys an inbound phone number, creates an Elastic SIP Trunk, points its
Origination URL at the LiveKit SIP gateway (PROP-102), and attaches the
number to the trunk so inbound PSTN calls route to LiveKit.

Usage:
    cp .env.example .env   # fill in TWILIO_ACCOUNT_SID / TWILIO_AUTH_TOKEN
    pip install -r requirements.txt
    python provision_sip_trunk.py
"""

import os
import sys

from dotenv import load_dotenv
from twilio.rest import Client
from twilio.base.exceptions import TwilioRestException

load_dotenv()

ACCOUNT_SID = os.environ.get("TWILIO_ACCOUNT_SID")
AUTH_TOKEN = os.environ.get("TWILIO_AUTH_TOKEN")
NUMBER_COUNTRY = os.environ.get("TWILIO_NUMBER_COUNTRY", "US")
NUMBER_AREA_CODE = os.environ.get("TWILIO_NUMBER_AREA_CODE")
TRUNK_FRIENDLY_NAME = os.environ.get("TWILIO_TRUNK_FRIENDLY_NAME", "propview-voice-agent")
ORIGINATION_URI = os.environ.get("LIVEKIT_SIP_ORIGINATION_URI")


def require_credentials() -> Client:
    if not ACCOUNT_SID or not AUTH_TOKEN:
        sys.exit(
            "Missing TWILIO_ACCOUNT_SID / TWILIO_AUTH_TOKEN.\n"
            "Copy .env.example to .env and fill in your Twilio credentials."
        )
    return Client(ACCOUNT_SID, AUTH_TOKEN)


def buy_phone_number(client: Client) -> str:
    search = client.available_phone_numbers(NUMBER_COUNTRY).local.list(
        area_code=NUMBER_AREA_CODE, voice_enabled=True, limit=1
    )
    if not search:
        sys.exit(
            f"No available voice-enabled numbers found for country={NUMBER_COUNTRY} "
            f"area_code={NUMBER_AREA_CODE}. Try a different area code."
        )
    candidate = search[0].phone_number
    purchased = client.incoming_phone_numbers.create(phone_number=candidate)
    print(f"Purchased DID: {purchased.phone_number} (sid={purchased.sid})")
    return purchased.sid


def create_trunk(client: Client) -> str:
    trunk = client.trunking.v1.trunks.create(friendly_name=TRUNK_FRIENDLY_NAME)
    print(f"Created SIP trunk: {trunk.friendly_name} (sid={trunk.sid})")

    if ORIGINATION_URI:
        trunk_ctx = client.trunking.v1.trunks(trunk.sid)
        trunk_ctx.origination_urls.create(
            friendly_name="livekit-sip-gateway",
            sip_url=ORIGINATION_URI,
            weight=10,
            priority=10,
            enabled=True,
        )
        print(f"Set origination URL -> {ORIGINATION_URI}")
    else:
        print(
            "LIVEKIT_SIP_ORIGINATION_URI not set — trunk created without an "
            "origination URL. Set it once PROP-102 (LiveKit SIP gateway) is live, "
            "then re-run this script or add it via the Twilio console."
        )

    return trunk.sid


def attach_number_to_trunk(client: Client, trunk_sid: str, phone_number_sid: str) -> None:
    client.trunking.v1.trunks(trunk_sid).phone_numbers.create(phone_number_sid=phone_number_sid)
    print(f"Attached phone number {phone_number_sid} to trunk {trunk_sid}")


def main() -> None:
    client = require_credentials()
    try:
        phone_number_sid = buy_phone_number(client)
        trunk_sid = create_trunk(client)
        attach_number_to_trunk(client, trunk_sid, phone_number_sid)
    except TwilioRestException as exc:
        sys.exit(f"Twilio API error: {exc}")

    print(
        "\nDone. Record trunk_sid and the purchased number somewhere PROP-102 "
        "(LiveKit SIP gateway setup) can read them — the gateway needs to accept "
        "inbound SIP from this trunk's termination URI."
    )


if __name__ == "__main__":
    main()
