# VAD / VAP Sidecar

Owner: Deepak (Dev B)

Silero VAD / Voice Activity Projection sidecar for predictive turn-taking —
detects when the caller is about to speak so the orchestrator can clear the
agent's playout buffer before audio overlaps.

- **PROP-202** — Deploy lightweight Silero VAD/VAP sidecar (quantized ONNX,
  runs on CPU workers per the plan's cost mitigation)
