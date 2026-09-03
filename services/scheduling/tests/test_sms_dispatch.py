"""
Tests for sms_dispatch.py -- mocks Twilio's Client (no real Twilio
Account SID/Auth Token available in this environment, see the module
docstring). Verifies routing/config logic and the confirmation message
body, not that Twilio's actual API accepts these requests.

Run: python -m pytest tests/test_sms_dispatch.py -v
"""

import sys
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import sms_dispatch
from sms_dispatch import SmsDispatchError, build_appointment_confirmation, send_sms, send_whatsapp


@pytest.fixture(autouse=True)
def twilio_env(monkeypatch):
    monkeypatch.setenv("TWILIO_ACCOUNT_SID", "AC_test")
    monkeypatch.setenv("TWILIO_AUTH_TOKEN", "token_test")
    monkeypatch.setenv("TWILIO_SMS_FROM_NUMBER", "+15125550000")
    monkeypatch.setenv("TWILIO_WHATSAPP_FROM_NUMBER", "+15125550001")


@pytest.mark.asyncio
async def test_send_sms_uses_configured_from_number():
    with patch("sms_dispatch.Client") as mock_client_cls:
        mock_client = MagicMock()
        mock_client.messages.create.return_value = MagicMock(sid="SM123")
        mock_client_cls.return_value = mock_client

        sid = await send_sms("+15125551234", "hello")

    assert sid == "SM123"
    mock_client.messages.create.assert_called_once_with(to="+15125551234", from_="+15125550000", body="hello")


@pytest.mark.asyncio
async def test_send_whatsapp_prefixes_numbers():
    with patch("sms_dispatch.Client") as mock_client_cls:
        mock_client = MagicMock()
        mock_client.messages.create.return_value = MagicMock(sid="SM456")
        mock_client_cls.return_value = mock_client

        sid = await send_whatsapp("+15125551234", "hello")

    assert sid == "SM456"
    mock_client.messages.create.assert_called_once_with(
        to="whatsapp:+15125551234", from_="whatsapp:+15125550001", body="hello"
    )


@pytest.mark.asyncio
async def test_send_sms_raises_clearly_without_from_number(monkeypatch):
    monkeypatch.delenv("TWILIO_SMS_FROM_NUMBER", raising=False)
    with pytest.raises(SmsDispatchError):
        await send_sms("+15125551234", "hello")


def test_get_client_raises_clearly_without_credentials(monkeypatch):
    monkeypatch.delenv("TWILIO_ACCOUNT_SID", raising=False)
    with pytest.raises(SmsDispatchError):
        sms_dispatch._get_client()


def test_build_appointment_confirmation_includes_key_details():
    body = build_appointment_confirmation("123 Oak St", "Tuesday at 2:00 PM", agency_name="Austin Realty")
    assert "Austin Realty" in body
    assert "123 Oak St" in body
    assert "Tuesday at 2:00 PM" in body
    assert "STOP" in body  # opt-out language, TCPA-relevant per the plan's compliance section


def test_build_appointment_confirmation_default_agency_name():
    body = build_appointment_confirmation("123 Oak St", "Tuesday at 2:00 PM")
    assert "Your agent" in body
