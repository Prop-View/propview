"""
Live integration test for PROP-105 against a real LiveKit server.

Not a pytest unit test -- it needs `livekit-server --dev` running locally
(see ../../infra/livekit/LOCAL_TESTING.md). Uses a fake Gemini session
(no API key needed) to isolate and verify the LiveKit plumbing itself:
room join, track publish/subscribe, and the AudioStream/AudioSource
sample-rate conversion the orchestrator relies on.

Run:
    livekit-server --dev &
    python test_orchestrator_live.py
"""

import asyncio
import math
import struct
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
sys.path.insert(0, str(Path(__file__).resolve().parent.parent.parent / "gemini-client"))

from livekit import api, rtc

from gemini_live_client import AudioChunk, TurnComplete
from orchestrator import GEMINI_INPUT_RATE_HZ, GEMINI_OUTPUT_RATE_HZ, CallOrchestrator
from session_store import SessionStore

LIVEKIT_URL = "ws://localhost:7880"
API_KEY = "devkey"
API_SECRET = "secret"
ROOM_NAME = "test-call-room"
CALLER_SIP_RATE = 8000  # mimics what livekit-sip would publish for a phone leg


def make_token(identity: str) -> str:
    grants = api.VideoGrants(room_join=True, room=ROOM_NAME, can_publish=True, can_subscribe=True)
    return api.AccessToken(API_KEY, API_SECRET).with_identity(identity).with_grants(grants).to_jwt()


def synth_tone(seconds: float, rate: int, freq: int = 300) -> bytes:
    n = int(seconds * rate)
    samples = [int(3000 * math.sin(2 * math.pi * freq * i / rate)) for i in range(n)]
    return struct.pack(f"<{n}h", *samples)


class FakeGeminiSession:
    """Echoes back whatever audio it receives, tagged with periodic TurnComplete."""

    def __init__(self):
        self.received_chunks: list[bytes] = []
        self._queue: asyncio.Queue = asyncio.Queue()
        self._chunks_since_turn = 0

    async def send_audio(self, pcm16_bytes: bytes) -> None:
        self.received_chunks.append(pcm16_bytes)
        await self._queue.put(AudioChunk(data=pcm16_bytes))
        self._chunks_since_turn += 1
        if self._chunks_since_turn >= 5:
            self._chunks_since_turn = 0
            await self._queue.put(TurnComplete())

    async def send_end_of_audio(self) -> None:
        pass

    async def receive_events(self):
        while True:
            yield await self._queue.get()


async def main() -> None:
    caller_room = rtc.Room()
    agent_room = rtc.Room()

    await caller_room.connect(LIVEKIT_URL, make_token("caller"))
    await agent_room.connect(LIVEKIT_URL, make_token("ai-agent"))
    print("Both participants connected.")

    session_store = SessionStore(redis_url="redis://localhost:6379")
    fake_gemini = FakeGeminiSession()
    orchestrator = CallOrchestrator(room=agent_room, gemini_session=fake_gemini, session_store=session_store)
    await orchestrator.start()

    session = await session_store.get_session(agent_room.name)
    print(f"Session store: {'created' if session else 'MISSING'} session for room {agent_room.name!r}")

    # Caller publishes a synthetic "phone leg" audio track, as livekit-sip would.
    caller_source = rtc.AudioSource(sample_rate=CALLER_SIP_RATE, num_channels=1)
    caller_track = rtc.LocalAudioTrack.create_audio_track("caller-voice", caller_source)
    await caller_room.local_participant.publish_track(
        caller_track, rtc.TrackPublishOptions(source=rtc.TrackSource.SOURCE_MICROPHONE)
    )
    print(f"Caller publishing synthetic {CALLER_SIP_RATE}Hz audio.")

    # Caller subscribes to whatever the agent publishes back.
    agent_frames_received: list[rtc.AudioFrame] = []
    agent_track_ready = asyncio.Event()

    def on_caller_track_subscribed(track, publication, participant):
        if track.kind != rtc.TrackKind.KIND_AUDIO:
            return
        print(f"Caller side subscribed to {participant.identity}'s track.")
        agent_track_ready.set()

        async def collect():
            stream = rtc.AudioStream.from_track(track=track, sample_rate=GEMINI_OUTPUT_RATE_HZ, num_channels=1)
            async for event in stream:
                agent_frames_received.append(event.frame)
                if len(agent_frames_received) >= 3:
                    return

        asyncio.create_task(collect())

    caller_room.on("track_subscribed", on_caller_track_subscribed)

    # Feed a few 20ms frames of synthetic "caller speech" at 8kHz.
    frame_samples = CALLER_SIP_RATE * 20 // 1000  # 160 samples/frame
    tone = synth_tone(seconds=2.0, rate=CALLER_SIP_RATE)
    for i in range(0, len(tone), frame_samples * 2):
        chunk = tone[i : i + frame_samples * 2]
        if len(chunk) < frame_samples * 2:
            break
        frame = rtc.AudioFrame(
            data=chunk, sample_rate=CALLER_SIP_RATE, num_channels=1, samples_per_channel=frame_samples
        )
        await caller_source.capture_frame(frame)
        await asyncio.sleep(0.02)

    try:
        await asyncio.wait_for(agent_track_ready.wait(), timeout=5)
    except TimeoutError:
        print("FAIL: caller never saw the agent's published track.")
        sys.exit(1)

    # Give the echo pipeline a moment to round-trip.
    for _ in range(50):
        if agent_frames_received:
            break
        await asyncio.sleep(0.1)

    print(f"\nGemini-side received {len(fake_gemini.received_chunks)} chunks.")
    if fake_gemini.received_chunks:
        sample_count = len(fake_gemini.received_chunks[0]) // 2
        print(f"  First chunk: {len(fake_gemini.received_chunks[0])} bytes = {sample_count} samples at 16kHz")

    print(f"Caller received {len(agent_frames_received)} frames back from the agent's published track.")
    if agent_frames_received:
        f = agent_frames_received[0]
        print(f"  First frame: sample_rate={f.sample_rate}, samples_per_channel={f.samples_per_channel}")

    ok = len(fake_gemini.received_chunks) > 0 and len(agent_frames_received) > 0 and session is not None
    print("\nRESULT:", "PASS" if ok else "FAIL")

    await orchestrator.aclose()
    session_after_close = await session_store.get_session(agent_room.name)
    print(f"Session after aclose(): {'still present (BUG)' if session_after_close else 'correctly removed'}")
    ok = ok and session_after_close is None

    await session_store.aclose()
    await caller_room.disconnect()
    await agent_room.disconnect()
    sys.exit(0 if ok else 1)


if __name__ == "__main__":
    asyncio.run(main())
