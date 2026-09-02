# PROP-103 / PROP-107: Audio Resampling Pipeline

Bidirectional 8kHz G.711 mu-law ↔ 16kHz PCM conversion. Native C for the
per-sample hot path, thin ctypes wrapper for everything else.

**Update from building PROP-105 (orchestrator):** this module is *not*
actually wired into the LiveKit↔Gemini path. Inspecting the LiveKit SDK
directly showed `AudioStream`/`AudioSource` do real sample-rate conversion
inside LiveKit's own media engine, so the orchestrator talks to Gemini's
16kHz/24kHz PCM directly and never sees raw G.711 — see
`../orchestrator/README.md` for the full explanation. This code is correct
and fully tested, and stays available for any future path that touches raw
G.711 outside LiveKit (e.g. a non-LiveKit fallback stack in Sprint 5), but
it's not currently on the hot path of a real call.

## Build & test

```bash
cd services/audio-pipeline
./build.sh                              # compiles csrc/resampler.c
pip install -r requirements.txt
python -m pytest tests/ -v
```

All 13 tests pass as of this writing, including a self-consistency check
on the mu-law codec (decode → encode → decode must never drift) and the
PROP-107 20ms-frame-size assertions (160 bytes @ 8kHz mu-law, 640 bytes @
16kHz PCM16).

## Design notes

- **mu-law decode** implements the standard ITU-T G.711 formula directly.
- **mu-law encode** is deliberately *not* a separate hand-written
  bit-manipulation routine — those are easy to get subtly wrong in a way
  that silently disagrees with the decoder. Instead it does a nearest-value
  search against the same 256-entry decode table, which is the actual
  definition of mu-law encoding ("which of the 256 representable codes
  decodes closest to this value") and makes disagreement between encode
  and decode structurally impossible.
- **Resampling is intentionally simple** for this MVP: linear interpolation
  for 8k→16k upsampling, box-car averaging for 16k→8k and 24k→8k
  decimation. This is adequate for voice-band audio (already band-limited
  well below Nyquist by G.711 itself) but is not a proper polyphase/FIR
  anti-aliasing filter. If real-call testing surfaces audible artifacts,
  swap in `scipy.signal.resample_poly` or `libsoxr` — the `audio_resampler.py`
  function signatures wouldn't need to change.

## API

```python
import audio_resampler as ar

# SIP -> Gemini (one 20ms frame: 160 bytes in, 640 bytes out)
gemini_frame = ar.sip_frame_to_gemini(ulaw_8k_frame)

# Gemini -> SIP (one 20ms frame: 1920 bytes in @ 24kHz, 160 bytes out)
sip_frame = ar.gemini_audio_to_sip(pcm16_24k_frame)
```

## Definition of Done (from Sprint Plan)

- [x] 8kHz mu-law ↔ 16kHz PCM resampling implemented in C, wrapped for Python.
- [x] Unit tests for 20ms audio frame chunking (PROP-107).
- [x] ~~Wired into the orchestrator (PROP-105)~~ — turned out not to be needed
      there; see the note above. Kept as a tested, reusable utility instead.
