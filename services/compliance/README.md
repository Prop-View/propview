# PROP-505 / PROP-506: Fair Housing Filter & PII Masking

Deterministic, rule-based pre-filter for demographic/steering questions —
defense in depth alongside `../prompts/system_prompt.py`'s instruction-based
handling, not a replacement for it.

## Honest scope note

Regex/keyword matching cannot guarantee catching every creatively-phrased
steering question. This filter requires **both** a protected-class term
**and** a demographic-question pattern in the same utterance (to avoid
false-flagging things like "is there a church nearby"), which catches the
common/obvious phrasings deterministically. Novel phrasing this filter
misses still has to be caught by the LLM's own judgment via the system
prompt. The Sprint Plan's "100% of demographic/steering questions"
Definition of Done realistically depends on both layers working together,
not this filter alone.

## Testing

```bash
python -m pytest tests/ -v
```

**Verified** 2026-09-03: 6/6 passing, including both of the Sprint Plan's
own scenario-15 examples verbatim ("Are the local residents mostly
white?", "Is this a Christian neighborhood?") plus a false-positive
control set of 15 ordinary questions drawn from the plan's other test
scenarios (pricing, school ratings, distance, frustration, human handoff,
etc.) — none of which get flagged.

One real bug the tests caught before shipping: the original term list only
matched *specific* protected-class instances ("christian", "muslim"), so
"What's the majority religion in that neighborhood?" slipped through.
Fixed by adding the generic category terms (religion, race, ethnicity,
national origin, etc.) alongside specific instances.

## Definition of Done — PROP-505 (from Sprint Plan)

- [x] Filter implemented and tested against the plan's own example scenarios.
- [ ] Not wired into the orchestrator's live call flow yet, and it's a
      genuine open design problem, not just missing plumbing: Gemini's
      Live API starts generating (and streaming audio for) its own
      response as soon as it detects end-of-speech, in the same turn
      `input_transcription` becomes available — there's no exposed
      primitive in the current integration to hold/cancel that in-flight
      audio if the transcription turns out to violate this filter after
      the fact. Properly solving this needs either a buffering strategy
      (delay playout until the transcription is checked, adding latency)
      or checking transcriptions on a rolling basis to catch violations
      before the *next* turn rather than the current one. Left as a
      standalone, fully tested module rather than shipping a
      race-condition-prone partial integration.

---

## PROP-506: PII Masking (regex + Presidio)

`pii_masking.py` masks caller-identifying and financial PII
(`PERSON`, `PHONE_NUMBER`, `EMAIL_ADDRESS`, `CREDIT_CARD`, `US_SSN`,
`US_BANK_NUMBER`) in transcripts before they're stored in
`interactions.transcript` (`db/migrations/003_crm_schema.sql`).

Presidio's built-in recognizers are already a regex+NLP hybrid (phone/
email/credit-card/SSN are regex-based; `PERSON` uses spaCy NER) — that
combination is what "regex + Presidio" in the plan refers to, not a
separate hand-rolled layer stacked on top.

**Deliberately does not mask property addresses or prices** — those are
business data this CRM needs, not PII to hide from itself.

### Setup

```bash
cd services/compliance
pip install -r requirements.txt
python -m spacy download en_core_web_sm   # small model -- our recognizers are mostly regex-based anyway
```

### Testing

```bash
python -m pytest tests/test_pii_masking.py -v
```

**Verified** 2026-09-03: 10/10 passing — name, phone, email, credit card,
and SSN all correctly masked; addresses and prices correctly left alone.

One real, instructive bug the tests caught: the initial SSN test fixture
used `123-45-6789`, which Presidio **deliberately** deny-lists as a
well-known canonical placeholder/example SSN — not a bug in Presidio or
this code, but in the test itself for picking the one SSN Presidio is
specifically built to ignore. Traced via Presidio's own
`UsSsnRecognizer.invalidate_result()` source rather than assumed, then
fixed by using a non-placeholder number in the test.

### Definition of Done — PROP-506 (from Sprint Plan)

- [x] PII masking implemented (regex + Presidio) and tested.
- [x] Wired into the actual write path for `interactions.transcript` —
      `../orchestrator/transcript_store.py` (added after this README was
      first written): Gemini's speech transcription feeds a per-call
      buffer, masked via this module and persisted when the call ends.
      See `../orchestrator/README.md`'s transcript section.

---

## PROP-508: Compliance Rules & Escalation Workflows

See [`COMPLIANCE_AND_ESCALATION.md`](COMPLIANCE_AND_ESCALATION.md) —
consolidates this filter, PII masking, the multi-region regulatory
surface (US/India/UAE — what's implemented vs. explicitly not), and the
human/fallback escalation workflows (PROP-501-504).
