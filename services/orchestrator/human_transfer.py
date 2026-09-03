"""
PROP-503: Transfers the caller's SIP leg directly to a human broker's
phone number.

This architecture never terminates SIP itself -- Twilio hands the call
off to LiveKit's SIP gateway (infra/livekit/), which is what actually
holds the SIP dialog with the telephony carrier. So "SIP REFER" here
means LiveKit's own `TransferSIPParticipant` API (a blind/cold transfer:
the caller's SIP leg is handed off to `transfer_to`, and they leave this
LiveKit room entirely), not something this service does by speaking raw
SIP to a carrier directly.

**Not live-verified**: needs a real LiveKit SIP deployment with an actual
inbound SIP participant to transfer (PROP-101/102 aren't deployed) --
same category of gap as everything else in this codebase gated on real
telephony infra. `receive_events`-driven unit tests
(tests/test_human_transfer.py) mock `LiveKitAPI.sip.transfer_sip_participant`
to verify the request shape and orchestrator-side dispatch logic.
"""

from __future__ import annotations

from livekit import api


async def transfer_to_broker(
    lk_api: api.LiveKitAPI, room_name: str, caller_identity: str, broker_phone_number: str
) -> api.TransferSIPParticipantResponse:
    return await lk_api.sip.transfer_sip_participant(
        api.TransferSIPParticipantRequest(
            participant_identity=caller_identity,
            room_name=room_name,
            transfer_to=broker_phone_number,
            play_dialtone=True,
        )
    )
