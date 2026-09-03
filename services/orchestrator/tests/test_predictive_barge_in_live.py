"""
Live end-to-end verification for PROP-202/203: does the VAP sidecar's
predictive CLEAR_BUFFER signal actually fire against a real LiveKit call,
with the real Silero ONNX model running on real speech audio -- not just
the fakes in test_orchestrator_barge_in.py / vap-sidecar's own unit tests.

Not a pytest unit test -- needs `livekit-server --dev` running locally
(see ../../infra/livekit/LOCAL_TESTING.md), same as test_orchestrator_live.py.

Scenario: a FakeGemini session streams continuous "agent speaking" audio
back the instant it receives anything (so the agent is reliably mid-turn),
then the caller publishes real recorded speech
(../../vap-sidecar/tests/fixtures/sample_speech.wav) partway through.
Passes if the VAD detects that speech onset and clears the playout queue
*before* any Gemini-side Interrupted event would (this fake Gemini never
sends one) -- i.e. the predictive path alone is sufficient to barge in.

Run:
    livekit-server --dev &
    python tests/test_predictive_barge_in_live.py
"""

import asyncio
import struct
import sys
import wave
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
sys.path.insert(0, str(Path(__file__).resolve().parent.parent.parent / "gemini-client"))
sys.path.insert(0, str(Path(__file__).resolve().parent.parent.parent / "vap-sidecar"))

from livekit import api, rtc

from gemini_live_client import AudioChunk
from orchestrator import GEMINI_INPUT_RATE_HZ, GEMINI_OUTPUT_RATE_HZ, CallOrchestrator
from vap_processor import SpeechActivityDetector

LIVEKIT_URL = "ws://localhost:7880"
API_KEY = "devkey"
API_SECRET = "secret"
ROOM_NAME = "test-predictive-bargein-room"
FIXTURE = Path(__file__).resolve().parent.parent.parent / "vap-sidecar" / "tests" / "fixtures" / "sample_speech.wav"


def make_token(identity: str) -> str:
    grants = api.VideoGrants(room_join=True, room=ROOM_NAME, can_publish=True, can_subscribe=True)
    return api.AccessToken(API_KEY, API_SECRET).with_identity(identity).with_grants(grants).to_jwt()


def synth_silence(seconds: float, rate: int) -> bytes:
    return b"\x00\x00" * int(seconds * rate)


class ContinuouslyTalkingFakeGemini:
    """Simulates an agent mid-utterance: emits a steady stream of AudioChunk
    events regardless of caller input, and never sends its own Interrupted
    event -- isolates whether the VAP predictive path alone triggers the
    buffer clear."""

    def __init__(self):
        self._queue: asyncio.Queue = asyncio.Queue()
        self._task = asyncio.create_task(self._talk_forever())

    async def _talk_forever(self) -> None:
        chunk = synth_silence(0.1, GEMINI_OUTPUT_RATE_HZ)  # 100ms of "speech" per chunk
        while True:
            await self._queue.put(AudioChunk(data=chunk))
            await asyncio.sleep(0.1)

    async def send_audio(self, pcm16_bytes: bytes) -> None:
        pass  # caller audio isn't echoed in this scenario -- only VAD sees it

    async def send_end_of_audio(self) -> None:
        pass

    async def receive_events(self):
        while True:
            yield await self._queue.get()

    def stop(self) -> None:
        self._task.cancel()


async def main() -> None:
    caller_room = rtc.Room()
    agent_room = rtc.Room()

    await caller_room.connect(LIVEKIT_URL, make_token("caller"))
    await agent_room.connect(LIVEKIT_URL, make_token("ai-agent"))
    print("Both participants connected.")

    fake_gemini = ContinuouslyTalkingFakeGemini()
    vad = SpeechActivityDetector()
    orchestrator = CallOrchestrator(room=agent_room, gemini_session=fake_gemini, vad_detector=vad)
    await orchestrator.start()

    # The fake Gemini keeps "talking" continuously regardless of
    # interruption (unlike the real Gemini Live API, which stops sending
    # audio once it recognizes an interruption) -- so _agent_speaking can
    # flip back to True moments after the predictive clear, once the next
    # simulated AudioChunk arrives. That's a fake-Gemini artifact, not a
    # bug: what actually matters is what _agent_speaking was AT THE MOMENT
    # clear_queue() fired, which this spy captures.
    clear_queue_calls = []
    agent_speaking_at_clear = []
    original_clear_queue = orchestrator._publish_source.clear_queue

    def spy_clear_queue():
        clear_queue_calls.append(True)
        agent_speaking_at_clear.append(orchestrator._agent_speaking)
        return original_clear_queue()

    orchestrator._publish_source.clear_queue = spy_clear_queue

    # Let the agent get reliably into "speaking" state before the caller
    # says anything.
    await asyncio.sleep(0.5)
    assert orchestrator._agent_speaking, "setup bug: agent never started 'speaking'"
    print("Agent is speaking (simulated). Now publishing real caller speech...")

    caller_source = rtc.AudioSource(sample_rate=GEMINI_INPUT_RATE_HZ, num_channels=1)
    caller_track = rtc.LocalAudioTrack.create_audio_track("caller-voice", caller_source)
    await caller_room.local_participant.publish_track(
        caller_track, rtc.TrackPublishOptions(source=rtc.TrackSource.SOURCE_MICROPHONE)
    )

    with wave.open(str(FIXTURE), "rb") as w:
        assert w.getframerate() == GEMINI_INPUT_RATE_HZ
        pcm = w.readframes(w.getnframes())

    frame_samples = GEMINI_INPUT_RATE_HZ * 20 // 1000  # 20ms frames, matches LiveKit's typical cadence
    frame_bytes = frame_samples * 2
    for i in range(0, len(pcm), frame_bytes):
        chunk = pcm[i : i + frame_bytes]
        if len(chunk) < frame_bytes:
            break
        frame = rtc.AudioFrame(
            data=chunk, sample_rate=GEMINI_INPUT_RATE_HZ, num_channels=1, samples_per_channel=frame_samples
        )
        await caller_source.capture_frame(frame)
        await asyncio.sleep(0.02)
        if clear_queue_calls:
            break  # no need to play the whole 8s clip once it's triggered

    await asyncio.sleep(0.3)  # let any in-flight track_subscribed/forwarding tasks settle

    print(f"\nclear_queue() called {len(clear_queue_calls)} time(s) via the predictive VAP path.")
    print(f"_agent_speaking at the moment of that call: {agent_speaking_at_clear} (expected [False] -- ")
    print("the interrupt handler flips it False before clearing the queue, proving the predictive")
    print("path actually ran the 'was this really an interruption' check before acting.")

    ok = len(clear_queue_calls) >= 1 and agent_speaking_at_clear and agent_speaking_at_clear[0] is False
    print("\nRESULT:", "PASS" if ok else "FAIL")

    fake_gemini.stop()
    await orchestrator.aclose()
    await caller_room.disconnect()
    await agent_room.disconnect()
    sys.exit(0 if ok else 1)


if __name__ == "__main__":
    asyncio.run(main())
