# PROP-402 / PROP-405: Lead Qualification Engine

BANT (Budget, Authority, Need, Timeline) extraction and lead scoring.

## Where the actual code lives

- **PROP-402 (BANT extraction)**: `../tool-router/tools/update_lead_qualification.py`,
  not a file in this directory. Gemini extracts BANT fields as a *function
  call* during natural conversation (the same mechanism `search_properties`
  already uses) rather than a separate NLP pass over the transcript — see
  that tool's docstring and `../tool-router/README.md` for the full
  reasoning. `../prompts/bant_conversation_design.md` (PROP-408) is the
  question-flow spec it implements against; `../prompts/system_prompt.py`
  is what actually instructs Gemini to call it.
- **PROP-405 (lead scoring)**: `lead_scoring.py`, right here — a pure
  function with no DB/service dependency, imported directly by the tool
  above every time a lead's BANT state changes.

This directory only holds the scoring rules because that's the one piece
that's genuinely standalone logic; the extraction itself is inseparable
from the live tool-calling conversation loop and belongs with the other
tools it's dispatched alongside.

## Scoring rules (`lead_scoring.py`)

A small ordered rules table over `intent`/`budget_min`/`budget_max`/`timeline`
— not a model, since these are already structured/categorical fields (no
NLP needed) and the plan explicitly calls this a "rules engine":

| Priority | Condition |
|---|---|
| **Low** | `intent == "browsing"`, `timeline == "exploring"`, or nothing captured yet |
| **High** | urgent timeline (`immediate`/`1-3mo`) **and** a budget **and** real transact intent (buy/sell/rent) |
| **Medium** | urgent timeline alone, OR budget + real intent without urgent timeline, OR `6mo+` timeline with a budget |
| **Low** | anything else (e.g. intent alone with no budget/timeline) |

Re-run on every `update_lead_qualification` call, so `leads.priority`
always reflects the fullest picture captured so far in the call, not a
one-time snapshot at first contact.

## Testing

```bash
cd services/lead-engine
python -m pytest tests/ -v
```

**Verified passing** 2026-09-04: 9/9 cases covering every branch of the
rules table. The extraction side (`update_lead_qualification`) is tested
in `../tool-router/tests/test_tool_router.py` against real Postgres —
contact/lead upsert, `COALESCE`-based partial updates, and re-scoring —
since it needs the DB the scoring function itself doesn't.

## Definition of Done (from Sprint Plan)

- [x] BANT qualification state extraction (as Gemini function calling,
      see above).
- [x] Lead scoring rules engine, High/Medium/Low priority tagger.
- [x] Live-verified against a real Gemini call actually deciding to call
      `update_lead_qualification` mid-conversation — 2026-09-04, see
      `../orchestrator/README.md`'s "Lead qualification context" section.
