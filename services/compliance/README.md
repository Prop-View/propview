# Compliance & PII

Owner: Deepak (filters) / Aahil (PII/DB)

Fair Housing / regulatory guardrails and PII redaction. Per the architecture
reference, compliance scope extends beyond the plan's US Fair Housing focus
to include GDPR and DPDP (India) — see `../../docs/architecture.md`.

- **PROP-505** — Fair Housing compliance filter (blocks demographic/steering queries)
- **PROP-506** — Automated PII masking (regex + Presidio) for stored transcripts
- **PROP-508** — Compliance rules & escalation workflow documentation
