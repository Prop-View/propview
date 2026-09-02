# Cascaded Fallback Pipeline

Owner: Deepak (PROP-501) / Aahil (PROP-502)

Deepgram STT + GPT-4o-mini + Cartesia TTS cascade that takes over when the
native S2S model degrades or drops, plus the health monitor that triggers
the switch. Corresponds to Fallback-layer **A** in the architecture
reference (`../../docs/architecture.md`) — telephony-provider failover
(layer B) is separate, see `../../infra/telephony/`.

- **PROP-501** — Cascaded fallback pipeline (Deepgram + GPT-4o-mini + Cartesia)
- **PROP-502** — Health monitor auto-switching on S2S latency/drops
- **PROP-507** — Stress testing fallback switches during active calls
