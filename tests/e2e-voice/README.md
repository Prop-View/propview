# PROP-207 / PROP-604: E2E Voice Scenario Tests

`harness.py` + `scenarios.py` + `run_scenarios.py` — the 15-scenario
matrix from `Sprint Plan.md` section 3, run against a real Gemini
session and a real Tool Router.

## Scope decision: text-driven, not literal audio-injection

The plan describes this as "audio injection framework playing synthetic
WAV files into WebRTC streams." What's built here sends text via
`GeminiLiveSession.send_text` instead. This reaches the exact same
downstream logic (tool calling, transcript capture, turn-taking,
compliance filtering) that these 15 scenarios are actually testing —
none of them are about audio *quality*, they're about conversational
*behavior* — without the extra complexity and flakiness of synthesizing
and injecting WAV audio into a LiveKit room for each one.
`../../services/gemini-client/`'s own tests made the same call for the
same reason. See `harness.py`'s docstring for the full reasoning.

**12 of 15 scenarios implemented** — 3 are excluded, not silently
skipped (see `scenarios.py`'s docstring for exactly why each one):
- **#4** (mid-sentence interruption) needs real audio timing — already
  covered for real by `../../services/orchestrator/tests/test_predictive_barge_in_live.py`.
- **#10** (SIP REFER transfer) needs a real telephony deployment
  (PROP-101/102, not deployed); its tool-call-trigger half duplicates #9.
- **#11** (call-drop recovery SMS) describes a capability that **does
  not exist anywhere in this codebase** — no code saves state on an
  unexpected disconnect, no reconnect SMS is ever sent. A real, named
  gap, not something to fake a passing check for.

## Running it

```bash
# Once: Tool Router running with migrations applied and at least one
# property seeded for tenant "test-e2e-voice" (harness.py's default).
cd services/tool-router && uvicorn main:app --port 8000 &

cd tests/e2e-voice
python run_scenarios.py                     # all 12
python run_scenarios.py 1_simple_inquiry     # one, by name
```

Needs a real `GEMINI_API_KEY` (loaded from `services/gemini-client/.env`)
— every run costs real API calls, by design (there's no way to test "does
the AI actually pivot back to real estate" without asking a real model).

## Verification

Checks are keyword/substring matching against real LLM output, not
exact-match — inherent to grading a real model's response, not a
shortcut. A failure here is a real signal worth investigating.

**Verified passing** 2026-09-08, live-run against real Gemini + real
Tool Router + real Postgres: **12/12 scenarios passed**, after fixing
three real bugs the first live run caught (not hypothetical edge cases —
each one actually broke a scenario before the fix):
1. `harness.py` fetched only the Tool Router's remote tool schemas,
   never merging in the local-only `transfer_to_human_agent` declaration
   (`orchestrator.build_gemini_tools()`) — without it, Gemini had no way
   to know the tool existed, and scenario #9 correctly-but-unhelpfully
   apologized that it "wasn't able to transfer" instead of ever
   attempting the call.
2. Transcript capture was gated on `TranscriptChunk.finished == True`,
   which — for every multi-sentence agent reply observed — never
   actually arrived `True` before `TurnComplete` fired (confirmed by
   logging every chunk's `finished` flag through a full turn). Fixed by
   accumulating transcript text unconditionally. Flagged in `harness.py`
   as worth checking against `services/orchestrator/orchestrator.py`'s
   own transcript capture, which has the identical dependency.
3. Tool-call errors (e.g. `check_calendar_slots` on a tenant with no
   calendar configured — a real, expected 422) were left to propagate
   and abort the whole scenario, instead of being reported back to
   Gemini as an error response the way `orchestrator.py`'s own
   `_handle_tool_call` does — which is exactly what lets a real call
   recover gracefully and keep going.

One scenario (`2_reservation_site_visit`) also needed a genuine fix to
the *scenario itself*, not the harness: a single-turn version "failed"
because Gemini correctly asked a clarifying question (which property?)
instead of guessing — exactly per `bant_conversation_design.md`'s
"ask one clarifying question if ambiguous" rule. Fixed by adding the
caller's answer as a second turn.

Running the full 12-scenario matrix (or scaling to the plan's full 50)
on every commit is a real operational cost/time tradeoff for whoever
wires this into CI — each live run above took real Gemini API calls.

## Definition of Done (from Sprint Plan)

- [x] Automated interruption-scenario voice testing (PROP-207) — the
      audio-timing half is `test_predictive_barge_in_live.py`; the
      conversational half is scenario coverage here (minus #4, excluded
      for the reason above).
- [x] 12/15-scenario E2E test runner (PROP-604) — scaling to the plan's
      full 50 scenarios is straightforward (`scenarios.py`'s `Scenario`
      objects are the extension point) but not done here.
- [ ] Literal audio-injection (WAV files into a real WebRTC stream) —
      scope decision, see above.
- [ ] Full 50-scenario coverage — 12 implemented, 3 explicitly excluded
      with reasons, scaling further is real content-authoring work.
