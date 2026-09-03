# PROP-505: Fair Housing Compliance Filter

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

## Definition of Done (from Sprint Plan)

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
