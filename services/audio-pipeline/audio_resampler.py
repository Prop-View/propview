"""
PROP-103: Python wrapper around the C resampler (csrc/resampler.c).

Bridges the SIP leg (8kHz G.711 mu-law) and Gemini Live (16kHz PCM16 in,
24kHz PCM16 out -- see services/gemini-client/).

Build the native library first: ./build.sh
"""

from __future__ import annotations

import ctypes
import platform
from pathlib import Path

_LIB_NAME = "libresampler.dylib" if platform.system() == "Darwin" else "libresampler.so"
_LIB_PATH = Path(__file__).parent / _LIB_NAME

if not _LIB_PATH.exists():
    raise FileNotFoundError(
        f"{_LIB_PATH} not found. Build it first: cd {Path(__file__).parent} && ./build.sh"
    )

_lib = ctypes.CDLL(str(_LIB_PATH))

_lib.ulaw_to_pcm16.argtypes = [ctypes.POINTER(ctypes.c_uint8), ctypes.c_int, ctypes.POINTER(ctypes.c_int16)]
_lib.pcm16_to_ulaw.argtypes = [ctypes.POINTER(ctypes.c_int16), ctypes.c_int, ctypes.POINTER(ctypes.c_uint8)]
_lib.upsample_2x.argtypes = [ctypes.POINTER(ctypes.c_int16), ctypes.c_int, ctypes.POINTER(ctypes.c_int16)]
_lib.downsample_2x.argtypes = [ctypes.POINTER(ctypes.c_int16), ctypes.c_int, ctypes.POINTER(ctypes.c_int16)]


def ulaw_to_pcm16(ulaw_bytes: bytes) -> bytes:
    """Decode 8kHz G.711 mu-law bytes to 8kHz linear PCM16 bytes."""
    n = len(ulaw_bytes)
    in_buf = (ctypes.c_uint8 * n).from_buffer_copy(ulaw_bytes)
    out_buf = (ctypes.c_int16 * n)()
    _lib.ulaw_to_pcm16(in_buf, n, out_buf)
    return bytes(out_buf)


def pcm16_to_ulaw(pcm16_bytes: bytes) -> bytes:
    """Encode 8kHz linear PCM16 bytes to 8kHz G.711 mu-law bytes."""
    n = len(pcm16_bytes) // 2
    in_buf = (ctypes.c_int16 * n).from_buffer_copy(pcm16_bytes)
    out_buf = (ctypes.c_uint8 * n)()
    _lib.pcm16_to_ulaw(in_buf, n, out_buf)
    return bytes(out_buf)


def upsample_8k_to_16k(pcm16_8k_bytes: bytes) -> bytes:
    """Linear-interpolate 8kHz PCM16 up to 16kHz PCM16."""
    n = len(pcm16_8k_bytes) // 2
    in_buf = (ctypes.c_int16 * n).from_buffer_copy(pcm16_8k_bytes)
    out_buf = (ctypes.c_int16 * (n * 2))()
    _lib.upsample_2x(in_buf, n, out_buf)
    return bytes(out_buf)


def downsample_16k_to_8k(pcm16_16k_bytes: bytes) -> bytes:
    """Decimate 16kHz PCM16 down to 8kHz PCM16 (pairwise-average low-pass)."""
    n = len(pcm16_16k_bytes) // 2
    if n % 2 != 0:
        raise ValueError("downsample_16k_to_8k requires an even number of input samples")
    in_buf = (ctypes.c_int16 * n).from_buffer_copy(pcm16_16k_bytes)
    out_buf = (ctypes.c_int16 * (n // 2))()
    _lib.downsample_2x(in_buf, n, out_buf)
    return bytes(out_buf)


def sip_frame_to_gemini(ulaw_8k_bytes: bytes) -> bytes:
    """SIP leg -> Gemini: 8kHz mu-law -> 8kHz PCM16 -> 16kHz PCM16."""
    return upsample_8k_to_16k(ulaw_to_pcm16(ulaw_8k_bytes))


def gemini_audio_to_sip(pcm16_24k_bytes: bytes) -> bytes:
    """Gemini -> SIP leg: 24kHz PCM16 -> 8kHz PCM16 -> 8kHz mu-law.

    24000/8000 is an exact 3:1 ratio, so this decimates directly rather
    than routing through the 2x-only C downsampler.
    """
    return pcm16_to_ulaw(decimate_3x(pcm16_24k_bytes))


def decimate_3x(pcm16_bytes: bytes) -> bytes:
    """Decimate by an exact factor of 3 (24kHz -> 8kHz) via 3-sample box-car averaging."""
    n = len(pcm16_bytes) // 2
    if n % 3 != 0:
        raise ValueError("decimate_3x requires a sample count divisible by 3")
    in_buf = (ctypes.c_int16 * n).from_buffer_copy(pcm16_bytes)
    out_samples = [(in_buf[i] + in_buf[i + 1] + in_buf[i + 2]) // 3 for i in range(0, n, 3)]
    return bytes((ctypes.c_int16 * len(out_samples))(*out_samples))
