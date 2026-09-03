"""
PROP-503/504: Unit tests for _handle_transfer_to_human -- mocks
human_transfer.transfer_to_broker (LiveKit SIP) and sms_dispatch.send_sms
(Twilio), since no real SIP deployment or Twilio account is available in
this environment (see human_transfer.py's docstring). Verifies the
dispatch/degrade-gracefully logic itself.

Run: python -m pytest tests/test_human_transfer.py -v
"""

import sys
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
sys.path.insert(0, str(Path(__file__).resolve().parent.parent.parent / "gemini-client"))

from gemini_live_client import ToolCallRequest
from orchestrator import CallOrchestrator


class FakeRoom:
    name = "test-room"


@pytest.fixture
def gemini():
    session = MagicMock()
    session.send_tool_response = AsyncMock()
    return session


@pytest.fixture
def orchestrator(gemini):
    orch = CallOrchestrator(
        room=FakeRoom(),
        gemini_session=gemini,
        lk_api=MagicMock(),
        broker_phone_number="+15125559000",
    )
    orch._caller_identity = "sip-caller-123"
    orch._caller_phone_number = "+15125551234"
    return orch


@pytest.mark.asyncio
async def test_transfer_not_configured_replies_with_error(gemini):
    orch = CallOrchestrator(room=FakeRoom(), gemini_session=gemini)  # no lk_api/broker configured
    call = ToolCallRequest(id="1", name="transfer_to_human_agent", args={"reason": "wants a human"})

    with patch("orchestrator.transfer_to_broker") as mock_transfer:
        await orch._handle_transfer_to_human(call)

    mock_transfer.assert_not_called()
    gemini.send_tool_response.assert_called_once()
    _, kwargs = gemini.send_tool_response.call_args
    assert "error" in kwargs["response"]


@pytest.mark.asyncio
async def test_successful_transfer_sends_sms_then_transfers(orchestrator, gemini):
    call = ToolCallRequest(id="1", name="transfer_to_human_agent", args={"reason": "wants a human"})

    with (
        patch("orchestrator.send_sms", new=AsyncMock()) as mock_send_sms,
        patch("orchestrator.transfer_to_broker", new=AsyncMock()) as mock_transfer,
    ):
        await orchestrator._handle_transfer_to_human(call)

    mock_send_sms.assert_called_once()
    sms_args, _ = mock_send_sms.call_args
    assert sms_args[0] == "+15125559000"  # sent to the broker, not the caller
    assert "wants a human" in sms_args[1]

    mock_transfer.assert_called_once_with(orchestrator._lk_api, "test-room", "sip-caller-123", "+15125559000")

    gemini.send_tool_response.assert_called_once()
    _, kwargs = gemini.send_tool_response.call_args
    assert kwargs["response"] == {"status": "transferred"}


@pytest.mark.asyncio
async def test_sms_failure_does_not_block_the_transfer(orchestrator, gemini):
    from sms_dispatch import SmsDispatchError

    call = ToolCallRequest(id="1", name="transfer_to_human_agent", args={})

    with (
        patch("orchestrator.send_sms", new=AsyncMock(side_effect=SmsDispatchError("no creds"))),
        patch("orchestrator.transfer_to_broker", new=AsyncMock()) as mock_transfer,
    ):
        await orchestrator._handle_transfer_to_human(call)

    mock_transfer.assert_called_once()  # transfer still happened despite the SMS failure
    _, kwargs = gemini.send_tool_response.call_args
    assert kwargs["response"] == {"status": "transferred"}


@pytest.mark.asyncio
async def test_sip_transfer_failure_reports_error_to_gemini(orchestrator, gemini):
    call = ToolCallRequest(id="1", name="transfer_to_human_agent", args={})

    with (
        patch("orchestrator.send_sms", new=AsyncMock()),
        patch("orchestrator.transfer_to_broker", new=AsyncMock(side_effect=RuntimeError("SIP error"))),
    ):
        await orchestrator._handle_transfer_to_human(call)

    _, kwargs = gemini.send_tool_response.call_args
    assert "error" in kwargs["response"]


@pytest.mark.asyncio
async def test_handle_tool_call_routes_transfer_locally_not_through_tool_client(gemini):
    """transfer_to_human_agent must never be forwarded to self._tool_client
    -- the Tool Router has no LiveKit access to act on it."""
    orch = CallOrchestrator(
        room=FakeRoom(), gemini_session=gemini, tool_client=MagicMock(), lk_api=MagicMock(), broker_phone_number="+1"
    )
    orch._caller_identity = "sip-caller"
    call = ToolCallRequest(id="1", name="transfer_to_human_agent", args={})

    with patch("orchestrator.send_sms", new=AsyncMock()), patch("orchestrator.transfer_to_broker", new=AsyncMock()):
        await orch._handle_tool_call(call)

    orch._tool_client.call_tool.assert_not_called()
