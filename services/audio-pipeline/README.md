# Audio Pipeline

Owner: Aahil (Dev A)

Bidirectional resampling between the SIP leg's 8kHz G.711 and the 16kHz PCM
the Gemini Live API expects, plus the frame-chunking unit tests.

- **PROP-103** — C/Rust-bound 8kHz G.711 ↔ 16kHz PCM resampler
- **PROP-107** — Unit tests for 20ms audio frame chunking
