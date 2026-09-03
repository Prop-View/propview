"""
PROP-202/PROP-207: Tests for the Silero VAD speech-activity detector.

Uses a real 8s speech+silence recording (tests/fixtures/sample_speech.wav,
trimmed from silero-vad's own MIT-licensed test fixture at
https://github.com/snakers4/silero-vad/blob/master/tests/data/test.wav)
run through the real ONNX model -- not mocked, since the whole point is to
verify actual speech/silence transitions are detected, and synthetic tones
don't exercise the model's real feature space.

Run: python -m pytest tests/test_vap_processor.py -v
"""

import sys
import wave
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from vap_processor import SAMPLE_RATE_HZ, SpeechActivityDetector

FIXTURE = Path(__file__).resolve().parent / "fixtures" / "sample_speech.wav"


def _read_pcm16(path: Path) -> bytes:
    with wave.open(str(path), "rb") as w:
        assert w.getframerate() == SAMPLE_RATE_HZ
        assert w.getnchannels() == 1
        assert w.getsampwidth() == 2
        return w.readframes(w.getnframes())


def test_detects_at_least_one_speech_start_and_end_in_real_audio():
    detector = SpeechActivityDetector()
    pcm = _read_pcm16(FIXTURE)

    events = detector.process(pcm)

    kinds = [e.kind for e in events]
    assert "speech_started" in kinds
    assert "speech_ended" in kinds
    # First transition in this fixture is speech (starts near sample 0).
    assert kinds[0] == "speech_started"


def test_pure_silence_yields_no_events():
    detector = SpeechActivityDetector()
    silence = b"\x00\x00" * SAMPLE_RATE_HZ * 2  # 2s of digital silence

    events = detector.process(silence)

    assert events == []


def test_process_handles_arbitrary_chunk_sizes_not_aligned_to_window():
    # LiveKit delivers 20ms frames (640 bytes at 16kHz) -- not a multiple
    # of Silero's 512-sample/1024-byte window. Feed it that way and confirm
    # results match feeding the whole buffer at once.
    pcm = _read_pcm16(FIXTURE)

    whole = SpeechActivityDetector().process(pcm)

    chunked_detector = SpeechActivityDetector()
    chunk_size = 640
    chunked_events = []
    for i in range(0, len(pcm), chunk_size):
        chunked_events.extend(chunked_detector.process(pcm[i : i + chunk_size]))

    assert [e.kind for e in chunked_events] == [e.kind for e in whole]


def test_reset_clears_state_and_buffer():
    detector = SpeechActivityDetector()
    pcm = _read_pcm16(FIXTURE)
    detector.process(pcm[:4000])  # partial window left in the buffer

    detector.reset()

    assert detector._byte_buffer == bytearray()
    # A clean re-run after reset should reproduce the first event.
    events = detector.process(pcm)
    assert events[0].kind == "speech_started"
