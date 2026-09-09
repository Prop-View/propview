"""
PROP-40/507: Live stress test for the cascaded fallback switch
(PROP-501/502) under an actual in-progress call with real LiveKit audio
flowing -- not just the mocked-session unit tests in
../../orchestrator/tests/test_fallback_switch.py.

Real Deepgram/OpenAI/Cartesia credentials aren't available in this
environment (see ../README.md), so the fallback session here is a fake
that still produces real AudioChunk events at the right sample rate --
what's under test is the SWITCH MECHANISM under live audio and repeated
failures, not the real cascade's own STT/LLM/TTS behavior (that's
../tests/test_cascaded_session.py's job).

Not a pytest unit test -- needs a real LiveKit server, same as
../../orchestrator/tests/test_predictive_barge_in_live.py.

Run:
    livekit-server --dev &
    python test_fallback_stress_live.py
"""

from __future__ import annotations

import asyncio
import sys
import wave
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))  # this dir's own health_monitor.py
sys.path.insert(0, str(Path(__file__).resolve().parent.parent.parent / "orchestrator"))
sys.path.insert(0, str(Path(__file__).resolve().parent.parent.parent / "gemini-client"))
sys.path.insert(0, str(Path(__file__).resolve().parent.parent.parent / "vap-sidecar"))

from livekit import api, rtc

from gemini_live_client import AudioChunk
from health_monitor import HealthMonitor
from orchestrator import GEMINI_INPUT_RATE_HZ, GEMINI_OUTPUT_RATE_HZ, CallOrchestrator

LIVEKIT_URL = "ws://localhost:7880"
API_KEY = "devkey"
API_SECRET = "secret"
ROOM_NAME = "test-fallback-stress-room"
FIXTURE = Path(__file__).resolve().parent.parent.parent / "vap-sidecar" / "tests" / "fixtures" / "sample_speech.wav"
STRESS_DURATION_SECONDS = 6


def make_token(identity: str) -> str:
    grants = api.VideoGrants(room_join=True, room=ROOM_NAME, can_publish=True, can_subscribe=True)
    return api.AccessToken(API_KEY, API_SECRET).with_identity(identity).with_grants(grants).to_jwt()


class FlakyPrimarySession:
    """Simulates a degrading connection: send_audio fails every Nth
    call. Never yields anything from receive_events() -- what's under
    test is the caller-audio-forwarding path's failure/switch handling,
    not this session's own output."""

    def __init__(self, fail_every: int = 4):
        self._fail_every = fail_every
        self._call_count = 0
        self.send_audio_calls = 0
        self.send_audio_failures = 0

    async def send_audio(self, pcm16_bytes: bytes) -> None:
        self._call_count += 1
        self.send_audio_calls += 1
        if self._call_count % self._fail_every == 0:
            self.send_audio_failures += 1
            raise RuntimeError("simulated connection drop")

    async def send_end_of_audio(self) -> None:
        pass

    async def send_tool_response(self, call_id, name, response) -> None:
        pass

    def receive_events(self):
        async def gen():
            while True:
                await asyncio.sleep(3600)
                yield  # pragma: no cover -- never actually reached

        return gen()


class WorkingFallbackSession:
    """Stands in for CascadedFallbackSession -- accepts audio without
    failing (by default) and produces a steady stream of real AudioChunk
    events, so a caller subscribed to the room's agent track actually
    receives audio after the switch (proving "no dead air", not just
    "the Python object changed"). `fail_after` optionally makes THIS
    session start failing too, after N calls -- for the second half of
    the stress scenario (see module docstring's "what happens when the
    fallback also fails" finding)."""

    def __init__(self, fail_after: int | None = None):
        self._fail_after = fail_after
        self.send_audio_calls = 0
        self.send_audio_failures = 0
        self.entered = False
        self.exited = False
        self._queue: asyncio.Queue = asyncio.Queue()
        self._talk_task: asyncio.Task | None = None

    async def __aenter__(self) -> "WorkingFallbackSession":
        self.entered = True
        self._talk_task = asyncio.create_task(self._talk_forever())
        return self

    async def __aexit__(self, *exc_info) -> None:
        self.exited = True
        if self._talk_task is not None:
            self._talk_task.cancel()

    async def _talk_forever(self) -> None:
        chunk = b"\x00\x00" * (GEMINI_OUTPUT_RATE_HZ * 100 // 1000)  # 100ms per chunk
        while True:
            await self._queue.put(AudioChunk(data=chunk))
            await asyncio.sleep(0.1)

    async def send_audio(self, pcm16_bytes: bytes) -> None:
        self.send_audio_calls += 1
        if self._fail_after is not None and self.send_audio_calls > self._fail_after:
            self.send_audio_failures += 1
            raise RuntimeError("the fallback session itself is now also failing")

    async def send_end_of_audio(self) -> None:
        pass

    async def send_tool_response(self, call_id, name, response) -> None:
        pass

    def receive_events(self):
        async def gen():
            while True:
                yield await self._queue.get()

        return gen()


async def main() -> None:
    caller_room = rtc.Room()
    agent_room = rtc.Room()
    await caller_room.connect(LIVEKIT_URL, make_token("caller"))
    await agent_room.connect(LIVEKIT_URL, make_token("ai-agent"))
    print("Both participants connected.")

    primary = FlakyPrimarySession()
    # fail_after=30 -- lets the first switch (primary -> fallback) succeed
    # and stabilize before the fallback itself starts failing too, so the
    # two phases of the stress scenario are cleanly separated in the results.
    fallback = WorkingFallbackSession(fail_after=30)
    health_monitor = HealthMonitor(consecutive_errors_threshold=2)

    async def fallback_factory():
        await fallback.__aenter__()
        return fallback

    orchestrator = CallOrchestrator(
        room=agent_room,
        gemini_session=primary,
        health_monitor=health_monitor,
        fallback_session_factory=fallback_factory,
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

    caller_source = rtc.AudioSource(sample_rate=GEMINI_INPUT_RATE_HZ, num_channels=1)
    caller_track = rtc.LocalAudioTrack.create_audio_track("caller-voice", caller_source)
    await caller_room.local_participant.publish_track(
        caller_track, rtc.TrackPublishOptions(source=rtc.TrackSource.SOURCE_MICROPHONE)
    )
    await asyncio.wait_for(agent_track_ready.wait(), timeout=5)
    print("Caller subscribed to agent track. Streaming real speech continuously for "
          f"{STRESS_DURATION_SECONDS}s to stress the primary->fallback switch...")

    with wave.open(str(FIXTURE), "rb") as w:
        pcm = w.readframes(w.getnframes())
    frame_samples = GEMINI_INPUT_RATE_HZ * 20 // 1000
    frame_bytes = frame_samples * 2

    started = asyncio.get_event_loop().time()
    switched_at: float | None = None
    while asyncio.get_event_loop().time() - started < STRESS_DURATION_SECONDS:
        for i in range(0, len(pcm), frame_bytes):
            chunk = pcm[i : i + frame_bytes]
            if len(chunk) < frame_bytes:
                break
            frame = rtc.AudioFrame(
                data=chunk, sample_rate=GEMINI_INPUT_RATE_HZ, num_channels=1, samples_per_channel=frame_samples
            )
            await caller_source.capture_frame(frame)
            await asyncio.sleep(0.02)
            if switched_at is None and orchestrator._fallback_session is not None:
                switched_at = asyncio.get_event_loop().time() - started
            if asyncio.get_event_loop().time() - started >= STRESS_DURATION_SECONDS:
                break

    await asyncio.sleep(0.3)  # let in-flight forwarding settle

    print(f"\nPrimary session: {primary.send_audio_calls} send_audio calls, {primary.send_audio_failures} failures")
    print(f"Fallback session: {fallback.send_audio_calls} send_audio calls, {fallback.send_audio_failures} failures (post-fail_after)")
    print(f"Switch happened: {orchestrator._fallback_session is not None} (at ~{switched_at:.2f}s)" if switched_at else "Switch happened: False")
    print(f"Real audio frames received on agent track after switch: {len(agent_frames_received)}")
    print(f"Health monitor still shows should_fallback=True (stuck, never resets after the fallback's own failures): {health_monitor.should_fallback}")

    # The actual "stress" finding: once switched, _switch_to_fallback()
    # returns True unconditionally (self._fallback_session is already
    # set) -- so when the FALLBACK session itself started failing above
    # (fail_after=30), those errors get silently absorbed by
    # _send_audio_with_fallback's `except: ... if switched: return`
    # path instead of ever being reported or triggering a second,
    # different recovery action. There is no tertiary fallback and no
    # "give up and end the call" path. This is a real, currently-
    # unhandled gap -- confirmed here live, not assumed -- documented in
    # ../README.md rather than silently worked around.
    ok = (
        switched_at is not None
        and primary.send_audio_failures >= 2
        and len(agent_frames_received) > 0
        and fallback.send_audio_failures > 0  # confirms the fallback-also-fails scenario was actually exercised
    )
    print("\nRESULT:", "PASS" if ok else "FAIL")

    await orchestrator.aclose()
    await caller_room.disconnect()
    await agent_room.disconnect()
    sys.exit(0 if ok else 1)


if __name__ == "__main__":
    asyncio.run(main())
