"""
PROP-404: SMS/WhatsApp confirmation dispatch via Twilio's messaging API.

Twilio's Python SDK is synchronous (uses `requests` under the hood) --
every call here runs it in a thread via `asyncio.to_thread`, same
async-first treatment `calendar_client.py` gives the (also synchronous)
Google API client.

**Not live-verified**: no real Twilio Account SID/Auth Token available in
this environment -- same gap PROP-101's own docs already flag ("Twilio
Account SID/Auth Token... waiting on real account credentials"). Unit
tests (tests/test_sms_dispatch.py) mock the Twilio client to verify the
message body/routing logic without needing a real account.
"""

from __future__ import annotations

import asyncio
import os

from twilio.rest import Client


class SmsDispatchError(RuntimeError):
    pass


def _get_client() -> Client:
    account_sid = os.environ.get("TWILIO_ACCOUNT_SID")
    auth_token = os.environ.get("TWILIO_AUTH_TOKEN")
    if not account_sid or not auth_token:
        raise SmsDispatchError("TWILIO_ACCOUNT_SID / TWILIO_AUTH_TOKEN not set")
    return Client(account_sid, auth_token)


def _send_sync(to_number: str, from_number: str, body: str) -> str:
    message = _get_client().messages.create(to=to_number, from_=from_number, body=body)
    return message.sid


async def send_sms(to_number: str, body: str) -> str:
    from_number = os.environ.get("TWILIO_SMS_FROM_NUMBER")
    if not from_number:
        raise SmsDispatchError("TWILIO_SMS_FROM_NUMBER not set")
    return await asyncio.to_thread(_send_sync, to_number, from_number, body)


async def send_whatsapp(to_number: str, body: str) -> str:
    from_number = os.environ.get("TWILIO_WHATSAPP_FROM_NUMBER")
    if not from_number:
        raise SmsDispatchError("TWILIO_WHATSAPP_FROM_NUMBER not set")
    return await asyncio.to_thread(_send_sync, f"whatsapp:{to_number}", f"whatsapp:{from_number}", body)


def build_appointment_confirmation(address: str, scheduled_at_local: str, agency_name: str = "Your agent") -> str:
    """The plan's demo scenario: a confirmation text within 10s of booking.
    Kept short and unambiguous -- this is a transactional SMS, not a
    marketing one.

    `agency_name` defaults to a generic phrase: tenant branding isn't
    threaded through to the booking path yet (tenant_settings has no
    agency-display-name column -- only calendar credentials). Callers with
    a real agency name available should pass it explicitly."""
    return f"{agency_name}: your site visit at {address} is confirmed for {scheduled_at_local}. Reply STOP to opt out."


def build_no_show_followup(agency_name: str = "Your agent") -> str:
    """Sent once per missed appointment (../follow-up-manager/followup_scan.py).
    Deliberately doesn't repeat the missed time/address the way
    build_appointment_confirmation does -- that slot is no longer
    actionable by the time this fires; the goal is just to re-open the
    conversation, not remind the caller what they missed."""
    return (
        f"{agency_name}: we missed you at your scheduled site visit. "
        f"Still interested? Call us back or reply to this message to rebook. "
        f"Reply STOP to opt out."
    )


def build_nurture_followup(agency_name: str = "Your agent") -> str:
    """Sent once per lead who called in but never booked a site visit
    (../follow-up-manager/followup_scan.py)."""
    return (
        f"{agency_name}: still looking for your next property? "
        f"We're here whenever you're ready to schedule a visit. "
        f"Reply STOP to opt out."
    )
