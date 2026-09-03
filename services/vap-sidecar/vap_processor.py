"""
PROP-202: Silero VAD sidecar for predictive turn-taking / barge-in.

Runs in-process -- imported directly into the orchestrator's caller-audio
forwarding loop -- rather than as a separately-deployed networked service.
At an 80ms barge-in budget (PROP-203/204's target), an HTTP/RPC hop on
every 32ms audio window would burn a meaningful slice of that budget for
no benefit; this is the same call orchestrator.py already made for the
resampler (LiveKit's in-process audio path wins over a literal network
hop). "Sidecar" here means a logically separate, independently-testable
unit -- not a separate OS process. If this ever needs to scale off the
orchestrator's CPU (the plan's GPU-cost mitigation on Deepak's side is
"run quantized ONNX on CPU workers" -- plural), the class boundary here
is exactly where a gRPC/HTTP wrapper would go without touching callers.

Uses the `silero-vad` PyPI package, which bundles the ONNX model directly
(no runtime download), with onnx=True per the plan's mitigation for
PROP-202's "GPU compute overhead" risk.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Literal

import numpy as np
from silero_vad import VADIterator, load_silero_vad

SAMPLE_RATE_HZ = 16000
WINDOW_SAMPLES = 512  # Silero VAD v5+'s required fixed window at 16kHz (32ms)
WINDOW_BYTES = WINDOW_SAMPLES * 2  # 16-bit PCM


@dataclass
class SpeechEvent:
    kind: Literal["speech_started", "speech_ended"]
    sample_offset: int  # samples since this detector's stream started (or was last reset())


class SpeechActivityDetector:
    """Feed it raw 16kHz mono PCM16 bytes as they arrive, in whatever
    chunk size the caller happens to deliver (LiveKit frames won't
    generally line up with Silero's fixed 512-sample window) -- it
    buffers internally and yields a SpeechEvent for each start/end
    transition Silero detects.

    One instance per call: VADIterator carries hysteresis state
    (`triggered`, `temp_end`) across windows, so instances must not be
    shared between concurrent calls.
    """

    def __init__(
        self,
        threshold: float = 0.5,
        min_silence_duration_ms: int = 100,
        speech_pad_ms: int = 30,
    ):
        model = load_silero_vad(onnx=True)
        self._iterator = VADIterator(
            model,
            threshold=threshold,
            sampling_rate=SAMPLE_RATE_HZ,
            min_silence_duration_ms=min_silence_duration_ms,
            speech_pad_ms=speech_pad_ms,
        )
        self._byte_buffer = bytearray()

    def process(self, pcm16_bytes: bytes) -> list[SpeechEvent]:
        self._byte_buffer.extend(pcm16_bytes)
        events: list[SpeechEvent] = []
        while len(self._byte_buffer) >= WINDOW_BYTES:
            window_bytes = bytes(self._byte_buffer[:WINDOW_BYTES])
            del self._byte_buffer[:WINDOW_BYTES]
            pcm = np.frombuffer(window_bytes, dtype=np.int16).astype(np.float32) / 32768.0

            result = self._iterator(pcm)
            if result is None:
                continue
            if "start" in result:
                events.append(SpeechEvent(kind="speech_started", sample_offset=result["start"]))
            else:
                events.append(SpeechEvent(kind="speech_ended", sample_offset=result["end"]))
        return events

    def reset(self) -> None:
        """Clears hysteresis state and any partial window -- call between calls
        if an instance is ever reused (main.py currently makes a fresh one per
        call instead)."""
        self._iterator.reset_states()
        self._byte_buffer.clear()
