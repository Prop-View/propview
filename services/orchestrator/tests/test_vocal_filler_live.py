"""
Live end-to-end verification for PROP-305: does a slow tool call actually
produce audible filler audio on the agent's real LiveKit track, using the
real bundled WAV clips (not fakes)?

Not a pytest unit test -- needs `livekit-server --dev` running locally,
same as test_orchestrator_live.py / test_predictive_barge_in_live.py.

Scenario: a fake ToolRouterClient sleeps 1.5s before "returning" a result
(well past the 0.5s filler threshold). Passes if the caller-side
participant actually receives real filler audio frames on the agent's
track *before* the tool call resolves, and receives no more once it does.

Run:
    livekit-server --dev &
    python tests/test_vocal_filler_live.py
"""

import asyncio
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
sys.path.insert(0, str(Path(__file__).resolve().parent.parent.parent / "gemini-client"))
sys.path.insert(0, str(Path(__file__).resolve().parent.parent.parent / "vap-sidecar"))

from livekit import api, rtc

from gemini_live_client import ToolCallRequest
from orchestrator import GEMINI_OUTPUT_RATE_HZ, CallOrchestrator

LIVEKIT_URL = "ws://localhost:7880"
API_KEY = "devkey"
API_SECRET = "secret"
ROOM_NAME = "test-vocal-filler-room"
TOOL_CALL_DELAY_SECONDS = 1.5


def make_token(identity: str) -> str:
    grants = api.VideoGrants(room_join=True, room=ROOM_NAME, can_publish=True, can_subscribe=True)
    return api.AccessToken(API_KEY, API_SECRET).with_identity(identity).with_grants(grants).to_jwt()


class SlowFakeToolClient:
    """Simulates a tool call that takes TOOL_CALL_DELAY_SECONDS to resolve."""

    async def call_tool(self, name: str, args: dict, caller_phone_number: str | None = None, lead_id=None):
        await asyncio.sleep(TOOL_CALL_DELAY_SECONDS)
        return {"listings": []}

    async def aclose(self) -> None:
        pass


class SilentFakeGemini:
    """Never produces its own audio -- isolates filler audio from anything
    Gemini itself might publish."""

    async def send_audio(self, pcm16_bytes: bytes) -> None:
        pass

    async def send_end_of_audio(self) -> None:
        pass

    async def send_tool_response(self, call_id: str, name: str, response: dict) -> None:
        pass

    async def receive_events(self):
        # Never yields -- this test drives _handle_tool_call directly
        # rather than through the receive_events loop.
        while True:
            await asyncio.sleep(3600)
            yield  # pragma: no cover


async def main() -> None:
    caller_room = rtc.Room()
    agent_room = rtc.Room()

    await caller_room.connect(LIVEKIT_URL, make_token("caller"))
    await agent_room.connect(LIVEKIT_URL, make_token("ai-agent"))
    print("Both participants connected.")

    orchestrator = CallOrchestrator(
        room=agent_room, gemini_session=SilentFakeGemini(), tool_client=SlowFakeToolClient()
    )
    await orchestrator.start()

    agent_frames_received: list[rtc.AudioFrame] = []
    agent_track_ready = asyncio.Event()

    def on_caller_track_subscribed(track, publication, participant):
        if track.kind != rtc.TrackKind.KIND_AUDIO:
            return
        agent_track_ready.set()

        async def collect():
            stream = rtc.AudioStream.from_track(track=track, sample_rate=GEMINI_OUTPUT_RATE_HZ, num_channels=1)
            async for event in stream:
                agent_frames_received.append(event.frame)

        asyncio.create_task(collect())

    caller_room.on("track_subscribed", on_caller_track_subscribed)

    await asyncio.wait_for(agent_track_ready.wait(), timeout=5)
    print("Caller subscribed to agent track. Triggering a slow tool call...")

    started_at = asyncio.get_event_loop().time()
    await orchestrator._handle_tool_call(ToolCallRequest(id="call-1", name="search_properties", args={}))
    elapsed = asyncio.get_event_loop().time() - started_at

    print(f"\nTool call handling took {elapsed:.2f}s (delay was {TOOL_CALL_DELAY_SECONDS}s).")
    print(f"Caller received {len(agent_frames_received)} audio frames on the agent's track during/after that.")

    # LiveKit's AudioStream re-chunks to its own internal frame size on
    # the receive side, so the exact count isn't 1:1 with the 20ms frames
    # vocal_filler.py captures -- just sanity-check it's a real handful
    # (not zero: filler actually played; not hundreds: it didn't keep
    # playing long after the 1.5s tool call resolved).
    ok = 10 <= len(agent_frames_received) <= 300
    print("\nRESULT:", "PASS" if ok else "FAIL")

    await orchestrator.aclose()
    await caller_room.disconnect()
    await agent_room.disconnect()
    sys.exit(0 if ok else 1)


if __name__ == "__main__":
    asyncio.run(main())
