# Orchestrator (Core Brain)

Owner: Aahil (Dev A), with AI-side pieces from Deepak

The event loop wiring LiveKit audio frames to the Gemini S2S client, barge-in
handling, Redis-backed conversation state, and the vocal filler that masks
tool-call latency. Per the architecture reference, this runs on **LangGraph**
rather than a bespoke loop — see `../../docs/architecture.md`.

- **PROP-105** — Basic orchestrator event loop (LiveKit ↔ Gemini)
- **PROP-203** — `CLEAR_BUFFER` event bus signal (VAP → LiveKit audio queue)
- **PROP-204** — Transcript truncation in Redis context window on barge-in
- **PROP-305** — Interactive Vocal Filler generator for tool calls > 500ms
