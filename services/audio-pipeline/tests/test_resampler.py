"""
PROP-107: Unit tests for the audio pipeline, including 20ms frame chunking.

Run: cd services/audio-pipeline && python -m pytest tests/ -v
(build.sh must have been run first to produce the native library)
"""

import struct
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import audio_resampler as ar

FRAME_MS = 20
RATE_8K = 8000
RATE_16K = 16000
FRAME_SAMPLES_8K = RATE_8K * FRAME_MS // 1000  # 160 samples/frame
FRAME_SAMPLES_16K = RATE_16K * FRAME_MS // 1000  # 320 samples/frame


def pcm16_bytes(samples):
    return struct.pack(f"<{len(samples)}h", *samples)


def unpack_pcm16(b: bytes):
    return list(struct.unpack(f"<{len(b) // 2}h", b))


# ---- mu-law codec correctness ----


def test_ulaw_silence_codes_decode_to_zero():
    # 0x7F and 0xFF are the standard positive/negative "zero" codes in mu-law.
    assert ar.ulaw_to_pcm16(bytes([0x7F])) == pcm16_bytes([0])
    assert ar.ulaw_to_pcm16(bytes([0xFF])) == pcm16_bytes([0])


def test_ulaw_decode_extremes_are_near_full_scale():
    values = unpack_pcm16(ar.ulaw_to_pcm16(bytes([0x00, 0x80])))
    # byte 0x00 -> most negative representable sample, 0x80 -> its positive mirror
    assert values[0] < -32000
    assert values[1] > 32000 - 300  # allow for quantization near the top segment


def test_ulaw_roundtrip_is_within_quantization_error():
    original = [0, 100, -100, 1000, -1000, 8000, -8000, 20000, -20000, 32000, -32000]
    encoded = ar.pcm16_to_ulaw(pcm16_bytes(original))
    decoded = unpack_pcm16(ar.ulaw_to_pcm16(encoded))
    for orig, rt in zip(original, decoded):
        # mu-law is lossy/logarithmic; error grows with magnitude but should
        # stay well under 5% of full scale for any single sample here.
        assert abs(orig - rt) < 1600, f"{orig} -> {rt}"


def test_ulaw_encode_decode_is_self_consistent():
    # Every encodable byte, once decoded and re-encoded, must map back to
    # itself -- this is what "encoder = nearest match against decoder" guarantees.
    for code in range(256):
        decoded = unpack_pcm16(ar.ulaw_to_pcm16(bytes([code])))[0]
        re_encoded = ar.pcm16_to_ulaw(pcm16_bytes([decoded]))[0]
        re_decoded = unpack_pcm16(ar.ulaw_to_pcm16(bytes([re_encoded])))[0]
        assert re_decoded == decoded, f"code {code}: decode->encode->decode drifted"


# ---- resampling correctness ----


def test_upsample_doubles_length_and_preserves_original_samples():
    original = [100, 200, 300, -400, 0]
    up = unpack_pcm16(ar.upsample_8k_to_16k(pcm16_bytes(original)))
    assert len(up) == len(original) * 2
    # even-indexed output samples are exactly the original (interpolation
    # only fills in the odd-indexed midpoints)
    assert up[0::2] == original


def test_downsample_halves_length():
    original = list(range(0, 320, 2))  # 160 samples, arbitrary even ramp
    down = unpack_pcm16(ar.downsample_16k_to_8k(pcm16_bytes(original)))
    assert len(down) == len(original) // 2


def test_upsample_then_downsample_roundtrips_closely():
    # A smooth low-frequency waveform should survive 8k->16k->8k closely,
    # since linear interpolation + averaging is a reasonable low-pass pair
    # for band-limited voice content.
    import math

    original = [int(3000 * math.sin(2 * math.pi * 200 * i / RATE_8K)) for i in range(FRAME_SAMPLES_8K)]
    up = ar.upsample_8k_to_16k(pcm16_bytes(original))
    back = unpack_pcm16(ar.downsample_16k_to_8k(up))
    for a, b in zip(original, back):
        assert abs(a - b) < 200, f"{a} -> {b}"


def test_decimate_3x_24k_to_8k():
    n = FRAME_SAMPLES_8K * 3  # 480 samples at 24kHz = one 20ms frame
    original = [1000] * n
    out = struct.unpack(f"<{n // 3}h", ar.decimate_3x(pcm16_bytes(original)))
    assert len(out) == FRAME_SAMPLES_8K
    assert all(v == 1000 for v in out)


# ---- PROP-107: 20ms frame chunking ----


def chunk_frames(data: bytes, frame_size_bytes: int):
    return [data[i : i + frame_size_bytes] for i in range(0, len(data), frame_size_bytes)]


def test_8k_ulaw_20ms_frame_is_160_bytes():
    # mu-law is 1 byte/sample, so 20ms @ 8kHz = 160 samples = 160 bytes.
    assert FRAME_SAMPLES_8K == 160


def test_16k_pcm16_20ms_frame_is_640_bytes():
    # PCM16 is 2 bytes/sample, so 20ms @ 16kHz = 320 samples = 640 bytes.
    assert FRAME_SAMPLES_16K * 2 == 640


def test_chunking_a_full_second_of_ulaw_yields_50_frames():
    one_second = bytes(RATE_8K)  # 8000 bytes = 1 second of mu-law
    frames = chunk_frames(one_second, FRAME_SAMPLES_8K)
    assert len(frames) == 50
    assert all(len(f) == FRAME_SAMPLES_8K for f in frames)


def test_sip_frame_to_gemini_produces_one_20ms_16k_frame_per_8k_frame():
    ulaw_frame = bytes([0xFF] * FRAME_SAMPLES_8K)  # 160 bytes of silence
    gemini_frame = ar.sip_frame_to_gemini(ulaw_frame)
    assert len(gemini_frame) == FRAME_SAMPLES_16K * 2  # 640 bytes


def test_gemini_audio_to_sip_produces_correct_length_ulaw_frame():
    frame_samples_24k = FRAME_SAMPLES_8K * 3  # 480 samples = one 20ms frame at 24kHz
    pcm_24k = pcm16_bytes([500] * frame_samples_24k)
    sip_frame = ar.gemini_audio_to_sip(pcm_24k)
    assert len(sip_frame) == FRAME_SAMPLES_8K  # 160 mu-law bytes
