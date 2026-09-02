# Architecture Reference

Source of truth: `architecture-diagram.jpeg` ("AI Real-Estate Voice Agent –
Final Architecture", shared 2026-09-02), which refines and extends
`Sprint Plan.md`. Where the two differ or the plan is silent, this diagram
wins.

## Components

1. **Inbound Call** — Customer PSTN/mobile → SIP provider. **Twilio is
   primary**; **Telnyx and Plivo are backup providers** for automatic
   telephony failover → `infra/telephony/`
2. **Real-Time Communication (LiveKit)** — SIP Gateway + WebRTC room
   bridging caller and AI agent → `infra/livekit/`
3. **Audio Processing & Turn Management** — normalization, AEC, VAD/VAP,
   turn detection, barge-in handling → `services/audio-pipeline/`,
   `services/vap-sidecar/`
4. **AI Agent (Native S2S)** — LLM reasoning, conversation memory, intent
   detection, slot filling, response generation. Orchestrated via
   **LangGraph**, not a bespoke event loop → `services/orchestrator/`,
   `services/gemini-client/`
5. **Tools & Business Logic** — property search, availability, lead
   capture/scoring, scheduling, human handoff, notifications →
   `services/tool-router/`, `services/lead-engine/`, `services/scheduling/`
6. **Data & Knowledge Layer** — Property DB, pgvector Knowledge Base, CRM
   DB, and a **separate Lead Engine store** (not folded into CRM) →
   `db/`
7. **Monitoring & Observability** — Grafana dashboards, OpenTelemetry
   **and LangSmith** tracing, alerts → `infra/observability/`

## Fallback & Resilience Layer

Five distinct sub-systems (only (A) is detailed in the Sprint Plan text):

- **A. S2S → STT → LLM → TTS cascade** (Deepgram + GPT-4o-mini + Cartesia)
  → `services/fallback-pipeline/`
- **B. Telephony provider failover** (Twilio → Telnyx/Plivo) — new vs. the
  plan text → `infra/telephony/`
- **C. LiveKit/media reconnect** or region switch → `infra/livekit/`
- **D. AI degradation modes** — smaller/faster model, disable non-critical
  tools, cached/template responses → `services/orchestrator/`
- **E. Human agent escalation** with full conversation context handoff →
  `services/scheduling/`

## Cross-cutting infrastructure (not in the plan's task list)

- **Event bus**: Kafka/RabbitMQ for call/tool/lead/notification events.
- **Logs & audit**: OpenSearch/Loki, separate from the Grafana/OTel metrics path.
- **Compliance surface**: GDPR and DPDP (India), in addition to the plan's
  US Fair Housing/PII focus → `services/compliance/`

## Security & Governance (cross-cutting, all services)

TLS everywhere, RBAC & least privilege, PII masking/redaction, audit logs,
data retention policies, API rate limiting, GDPR/DPDP compliance.
