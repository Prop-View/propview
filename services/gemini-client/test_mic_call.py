"""
Standalone manual test for PROP-104: talk to Gemini Live via your mic/speakers.

No Twilio, LiveKit, or phone call needed — just a free Gemini API key. Run,
speak into your mic, and you should hear Gemini reply. This is the fastest
way to prove the client actually works end to end before wiring it into
the orchestrator (PROP-105).

Usage:
    pip install -r requirements.txt
    cp .env.example .env   # fill in GEMINI_API_KEY
    python test_mic_call.py
"""

import asyncio
import os
import sys

import sounddevice as sd
from dotenv import load_dotenv

from gemini_live_client import (
    INPUT_SAMPLE_RATE_HZ,
    OUTPUT_SAMPLE_RATE_HZ,
    AudioChunk,
    GeminiLiveSession,
    Interrupted,
    TurnComplete,
)

FRAME_MS = 20
INPUT_FRAME_SAMPLES = INPUT_SAMPLE_RATE_HZ * FRAME_MS // 1000  # 320 samples/frame, per PROP-107


async def mic_to_session(session: GeminiLiveSession) -> None:
    loop = asyncio.get_running_loop()
    queue: asyncio.Queue[bytes] = asyncio.Queue()

    def callback(indata, frames, time_info, status):
        if status:
            print(f"[mic] {status}", file=sys.stderr)
        loop.call_soon_threadsafe(queue.put_nowait, bytes(indata))

    with sd.RawInputStream(
        samplerate=INPUT_SAMPLE_RATE_HZ,
        blocksize=INPUT_FRAME_SAMPLES,
        channels=1,
        dtype="int16",
        callback=callback,
    ):
        print("Listening — speak now (Ctrl+C to stop)...")
        while True:
            frame = await queue.get()
            await session.send_audio(frame)


async def session_to_speaker(session: GeminiLiveSession) -> None:
    stream = sd.RawOutputStream(samplerate=OUTPUT_SAMPLE_RATE_HZ, channels=1, dtype="int16")
    stream.start()
    try:
        async for event in session.receive_events():
            if isinstance(event, AudioChunk):
                stream.write(event.data)
            elif isinstance(event, TurnComplete):
                print("[gemini] turn complete")
            elif isinstance(event, Interrupted):
                print("[gemini] interrupted")
    finally:
        stream.stop()
        stream.close()


async def main() -> None:
    load_dotenv()
    if not os.environ.get("GEMINI_API_KEY"):
        sys.exit(
            "Set GEMINI_API_KEY in .env "
            "(get one free at https://aistudio.google.com/apikey)"
        )

    async with GeminiLiveSession(
        system_instruction="You are a friendly, concise real estate assistant. Keep replies short."
    ) as session:
        await asyncio.gather(mic_to_session(session), session_to_speaker(session))


if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        print("\nStopped.")
