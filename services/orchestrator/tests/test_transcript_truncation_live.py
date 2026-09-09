"""
Live end-to-end verification for PROP-204: does a barge-in actually
truncate the agent's in-progress transcript buffer AND push the truncated
line to a real Redis conversation-context window -- not just the fakes in
test_orchestrator_barge_in.py.

Not a pytest unit test -- needs `livekit-server --dev` and a real Redis
running locally, same pattern as test_predictive_barge_in_live.py (which
this borrows its scenario setup from -- see that file for why the fake
Gemini and caller-speech-injection approach is what it is).

Scenario: a fake Gemini session streams continuous "agent speaking" audio
AND periodically emits TranscriptChunk deltas (as the real Gemini API
does while a spoken reply is being generated) so the agent's in-progress
transcript buffer has real accumulated text by the time the caller's real
recorded speech triggers a predictive barge-in. Passes if: the buffer is
flushed as one "(interrupted)"-tagged line in _transcript_lines, the
buffer itself is reset (not left to bleed into whatever's said next), and
that same line actually lands in Redis via a real ConversationContextStore.

Run:
    livekit-server --dev &
    redis-server &  (or brew services start redis)
    python tests/test_transcript_truncation_live.py
"""

import asyncio
import sys
import wave
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
sys.path.insert(0, str(Path(__file__).resolve().parent.parent.parent / "gemini-client"))
sys.path.insert(0, str(Path(__file__).resolve().parent.parent.parent / "vap-sidecar"))

from livekit import api, rtc

from conversation_context import ConversationContextStore
from gemini_live_client import AudioChunk, TranscriptChunk
from orchestrator import GEMINI_INPUT_RATE_HZ, GEMINI_OUTPUT_RATE_HZ, CallOrchestrator
from vap_processor import SpeechActivityDetector

LIVEKIT_URL = "ws://localhost:7880"
API_KEY = "devkey"
API_SECRET = "secret"
ROOM_NAME = "test-transcript-truncation-room"
REDIS_URL = "redis://localhost:6379"
FIXTURE = Path(__file__).resolve().parent.parent.parent / "vap-sidecar" / "tests" / "fixtures" / "sample_speech.wav"
PARTIAL_UTTERANCE_WORDS = ["This ", "house ", "has ", "four ", "bed"]  # deliberately cut off before "rooms"


def make_token(identity: str) -> str:
    grants = api.VideoGrants(room_join=True, room=ROOM_NAME, can_publish=True, can_subscribe=True)
    return api.AccessToken(API_KEY, API_SECRET).with_identity(identity).with_grants(grants).to_jwt()


def synth_silence(seconds: float, rate: int) -> bytes:
    return b"\x00\x00" * int(seconds * rate)


class TalkingAndTranscribingFakeGemini:
    """Like test_predictive_barge_in_live.py's ContinuouslyTalkingFakeGemini,
    but also emits TranscriptChunk deltas alongside the audio -- the real
    Gemini Live API streams both concurrently while generating a spoken
    reply, which is exactly the scenario PROP-204's truncation needs to be
    exercised against."""

    def __init__(self):
        self._queue: asyncio.Queue = asyncio.Queue()
        self._task = asyncio.create_task(self._talk_forever())

    async def _talk_forever(self) -> None:
        for word in PARTIAL_UTTERANCE_WORDS:
            await self._queue.put(AudioChunk(data=synth_silence(0.1, GEMINI_OUTPUT_RATE_HZ)))
            await self._queue.put(TranscriptChunk(speaker="agent", text=word, finished=False))
            await asyncio.sleep(0.1)
        # Keep "talking" (audio only, no more transcript) so the agent
        # stays mid-utterance until the caller's speech interrupts it.
        while True:
            await self._queue.put(AudioChunk(data=synth_silence(0.1, GEMINI_OUTPUT_RATE_HZ)))
            await asyncio.sleep(0.1)

    async def send_audio(self, pcm16_bytes: bytes) -> None:
        pass

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

    fake_gemini = TalkingAndTranscribingFakeGemini()
    vad = SpeechActivityDetector()
    context_store = ConversationContextStore(redis_url=REDIS_URL)
    await context_store.clear(ROOM_NAME)  # in case a previous failed run left state behind

    orchestrator = CallOrchestrator(
        room=agent_room, gemini_session=fake_gemini, vad_detector=vad, conversation_context=context_store
    )
    await orchestrator.start()

    # Let all 5 word chunks stream in (0.5s) and confirm the buffer
    # actually has accumulated text before triggering the interruption --
    # otherwise this would (vacuously) pass even if truncation were broken.
    await asyncio.sleep(0.6)
    buffer_before = orchestrator._transcript_buffer["agent"]
    print(f"Agent transcript buffer before barge-in: {buffer_before!r}")
    assert buffer_before, "setup bug: no transcript accumulated before the barge-in fires"
    assert orchestrator._agent_speaking, "setup bug: agent never started 'speaking'"

    print("Publishing real caller speech to trigger a predictive barge-in...")
    caller_source = rtc.AudioSource(sample_rate=GEMINI_INPUT_RATE_HZ, num_channels=1)
    caller_track = rtc.LocalAudioTrack.create_audio_track("caller-voice", caller_source)
    await caller_room.local_participant.publish_track(
        caller_track, rtc.TrackPublishOptions(source=rtc.TrackSource.SOURCE_MICROPHONE)
    )

    with wave.open(str(FIXTURE), "rb") as w:
        pcm = w.readframes(w.getnframes())
    frame_samples = GEMINI_INPUT_RATE_HZ * 20 // 1000
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
        if not orchestrator._agent_speaking:
            break  # barge-in fired

    await asyncio.sleep(0.3)  # let the fire-and-forget Redis-push task settle

    buffer_after = orchestrator._transcript_buffer["agent"]
    expected_text = "".join(PARTIAL_UTTERANCE_WORDS)
    expected_line = f"Agent: {expected_text} (interrupted)"
    in_memory_ok = orchestrator._transcript_lines == [expected_line] and buffer_after == ""
    print(f"\n_transcript_lines: {orchestrator._transcript_lines}")
    print(f"buffer after (should be empty): {buffer_after!r}")

    redis_lines = await context_store.get_lines(ROOM_NAME)
    redis_ok = (
        len(redis_lines) == 1
        and redis_lines[0].speaker == "agent"
        and redis_lines[0].text == expected_text
        and redis_lines[0].interrupted is True
    )
    print(f"Redis context window for this call: {redis_lines}")

    ok = in_memory_ok and redis_ok
    print("\nRESULT:", "PASS" if ok else "FAIL")

    fake_gemini.stop()
    await orchestrator.aclose()
    await context_store.clear(ROOM_NAME)
    await context_store.aclose()
    await caller_room.disconnect()
    await agent_room.disconnect()
    sys.exit(0 if ok else 1)


if __name__ == "__main__":
    asyncio.run(main())
