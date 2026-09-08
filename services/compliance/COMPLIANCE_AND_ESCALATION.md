# PROP-508: Compliance Rules & Escalation Workflows

Consolidates what's actually implemented for compliance (Fair Housing,
PII, disclosure) and escalation (human transfer, AI-engine fallback)
across `services/compliance/`, `services/prompts/`, and
`services/orchestrator/` — plus the multi-region regulatory surface the
architecture reference calls for and what of it is genuinely built vs.
still a gap. Status as of 2026-09-08.

## 1. Fair Housing / anti-steering (PROP-505)

Two layers, deliberately redundant:

1. **Deterministic pre-filter** — `fair_housing_filter.py`'s
   `check_fair_housing(text)`. Requires *both* a protected-class term
   (race, religion, national origin, familial status, disability, and
   locally-added classes like sexual orientation) *and* a
   demographic-question pattern in the same utterance, to avoid
   false-flagging ordinary questions ("is there a church nearby" must
   not trigger this). Returns a canned compliant redirect
   (`COMPLIANT_REDIRECT_RESPONSE`) or `None`.
2. **LLM instruction** — `system_prompt.py`'s "Fair Housing —
   non-negotiable" section, catching creatively-phrased steering
   questions the deterministic filter's keyword matching can't
   enumerate in advance.

**Known gap, not silently ignored**: the filter is a standalone, fully
tested module — **it is not wired into the live call flow.** This is a
genuine open design problem, not missing plumbing: Gemini Live starts
generating (and streaming audio for) its own response as soon as it
detects end-of-speech, in the same turn `input_transcription` becomes
available. There's no exposed primitive in the current integration to
hold or cancel that in-flight audio if the transcription turns out to
violate this filter after the fact. Two real options, neither built:
- Buffer playout until the transcription is checked (adds real latency
  to every single turn, not just violating ones — a bad trade for the
  common case to guard the rare one).
- Detect on the *caller's* finished `TranscriptChunk`
  (`orchestrator._record_transcript_chunk` already captures this) and,
  on a match, interrupt whatever Gemini is currently saying
  (`_publish_source.clear_queue()`, the same mechanism PROP-203's
  barge-in uses) and play a pre-recorded canned disclosure — architecturally
  possible using pieces that already exist (`vocal_filler.py`'s playback
  pattern), but not implemented here; left as a defined, scoped follow-up
  rather than a rushed partial integration.

The plan's "100% of demographic/steering questions" target realistically
depends on both layers working together once live-wired — today, only
the LLM instruction layer is actually in the live call path.

## 2. Mandatory AI disclosure (TCPA)

`system_prompt.py` now requires Gemini to disclose it's an AI assistant
within its first turn, regardless of what the caller says first (added
alongside this doc — previously the prompt had no explicit disclosure
requirement, a real compliance gap this review surfaced). Not yet
live-verified that Gemini reliably follows this in practice — no
scenario test exercises "does turn 1 always include the disclosure."

## 3. PII masking (PROP-506)

`pii_masking.py`'s `mask_pii()` — Presidio (regex+NER hybrid) over
`PERSON`/`PHONE_NUMBER`/`EMAIL_ADDRESS`/`CREDIT_CARD`/`US_SSN`/
`US_BANK_NUMBER`. Deliberately does not mask property addresses or
prices (core business data, not PII to hide from the CRM itself).

**Live-wired**, unlike the Fair Housing filter: `orchestrator.py`
captures Gemini's speech transcription into a per-call buffer as the
call happens, and `transcript_store.py` masks it via this module and
persists it to `interactions.transcript` when the call ends, with the
RLS tenant context set inside the same transaction as the insert. See
`../orchestrator/README.md`'s transcript section for the real bug this
caught (a bare `set_config()` outside the insert's transaction silently
lost the tenant context).

## 4. Multi-region regulatory surface

The plan's Sprint Plan.md section 6 names three regions with distinct
requirements. **Only the US column has any real implementation** — the
other two are explicitly not built, not silently assumed-covered:

| Region | Framework | Requirement | Status |
|---|---|---|---|
| **US** | TCPA & Fair Housing Act | AI disclosure | Implemented (§2 above) |
| **US** | TCPA & Fair Housing Act | Anti-steering guardrails | Partially implemented (§1 — LLM layer live, deterministic filter not wired) |
| **US** | TCPA | Prior express consent before automated *outbound* calling | **Not applicable yet** — this system only handles inbound calls; nothing here originates outbound calls to a consumer |
| **India** | DPDP Act 2023 & TRAI DND | Scrub against National DND registry before dialing | **Not built** — again, only relevant once outbound calling exists |
| **India** | DPDP Act 2023 | Consent manager, explicit opt-in capture | **Not built** — no consent-capture flow anywhere in this codebase |
| **India** | DPDP Act 2023 | Local data residency (store Indian citizen data in-region) | **Not built** — `db/migrations/` has no region-aware storage; one Postgres instance, wherever it's deployed |
| **UAE** | PDPL (Law 45/2021) | Explicit consent for recording/processing | **Not built** |
| **UAE** | TDRA | Licensed SIP trunking (e&/du) | **Not built** — `infra/telephony/` provisions Twilio only |
| **UAE** | PDPL | Cross-border data transfer restrictions | **Not built** |

**Why the gap is real, not an oversight**: the Sprint Plan's own section
10 ("Critical Technical Clarification Questions") asks which geography
launches first — that question was never answered in this codebase's
history (no memory/decision record of a chosen launch region), so
building India/UAE-specific compliance machinery would be guessing at
requirements for a market that may not be the pilot target. The US-only
scope built so far (Fair Housing, TCPA disclosure, PII masking) matches
what the plan's own demo scenarios and DoD criteria actually specify in
detail; India/UAE are named but never worked through to the same level
of concreteness in the plan text itself.

## 5. Escalation workflows

Two distinct kinds of escalation, both engine-agnostic by design (see
each's own README for full detail):

- **Human escalation (PROP-503/504)** — `services/orchestrator/human_transfer.py`
  + `pre_transfer_summary.py`. Triggered by the caller explicitly asking
  for a person (`system_prompt.py`'s "Transferring to a human" section
  instructs Gemini to call `transfer_to_human_agent` immediately, no
  clarifying questions). Sends a context SMS to the broker (caller phone,
  transfer reason, latest BANT snapshot, recent transcript) *before*
  hard-transferring the caller's SIP leg via LiveKit's
  `TransferSIPParticipant` API. Not live-verified (no real SIP deployment).
- **Engine escalation / fallback (PROP-501/502)** — `services/fallback-pipeline/`.
  Triggered automatically by `HealthMonitor` (response latency >1200ms or
  2 consecutive session errors), not by the caller. Swaps the active S2S
  engine from Gemini Live to the cascaded Deepgram→GPT-4o-mini→Cartesia
  pipeline mid-call. Each external client verified reaching its real API
  with a fake key; the swap mechanism is unit-tested; not yet exercised
  against a real live call.

Both share the same underlying property: the orchestrator's audio
pipeline (barge-in, transcript capture, PII masking, telemetry) doesn't
need to know which "mode" it's in — human transfer ends the call (caller
leaves the LiveKit room entirely), fallback keeps it going on a
different backend, and neither needs orchestrator-level special-casing
beyond the swap/transfer call itself.

## Definition of Done (from Sprint Plan)

- [x] Fair Housing filter implemented and tested (PROP-505) — not
      live-wired, documented above as a real open design problem.
- [x] TCPA AI-disclosure requirement in the system prompt.
- [x] PII masking implemented, tested, and live-wired into the transcript
      write path (PROP-506).
- [x] Human escalation workflow documented and implemented (PROP-503/504).
- [x] Engine-level fallback escalation documented and implemented
      (PROP-501/502).
- [ ] India (DPDP/TRAI) and UAE (PDPL/TDRA) compliance — not built,
      pending a launch-region decision this codebase's history doesn't
      contain.
- [ ] Consent management / outbound-calling compliance (TCPA prior
      consent, DND scrubbing) — not applicable yet, this system is
      inbound-only.
