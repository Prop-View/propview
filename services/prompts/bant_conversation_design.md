# PROP-408: BANT Conversation Design Matrix

Design spec for eliciting BANT (Budget, Authority, Need, Timeline) during
a call, naturally, without it sounding like an interrogation. This is the
question-flow/prompt-rules spec that PROP-402 (BANT extraction parser,
Sprint 4) implements against — not code, since PROP-402 doesn't exist yet.

## Principle: extract from natural conversation, don't run a script

The assistant should never ask all four fields back-to-back as a checklist.
Each field has a **trigger** (when to ask) and a **natural phrasing bank**
(so it doesn't sound robotic on repeat calls).

| Field | Trigger | Example phrasing | Extraction target |
|---|---|---|---|
| **Need** | Caller mentions any property interest | (usually volunteered — "I'm looking for a 3-bedroom house") | `intent`: buy / sell / rent / browsing; `property_type`, `beds`, `location` |
| **Budget** | After Need is established, before searching listings | "What price range did you have in mind?" / "Roughly what are you hoping to spend?" | `budget_min`, `budget_max` |
| **Timeline** | After a listing is discussed, or Budget is given | "When are you hoping to move?" / "Is this something you're looking to do soon, or just exploring for now?" | `timeline`: immediate / 1-3mo / 3-6mo / 6mo+ / exploring |
| **Authority** | Only if ambiguous from context (e.g. caller says "we") | "Will you be the one making the decision, or is someone else involved too?" | `decision_maker`: solo / joint / other |

## Rules

1. **Never ask a field the caller already answered unprompted.** If they
   opened with "My wife and I have $600k to spend on a 4-bedroom, moving
   this summer," that's Need + Budget + Timeline in one turn — extract all
   three, don't re-ask.
2. **Ask at most one BANT question per turn**, and only when it fits the
   conversation's natural next step (e.g. right before a search, right
   after discussing a specific listing).
3. **Authority is the lowest priority** — many callers won't need it asked
   directly at all if context makes it obvious (a single caller referring
   to themselves).
4. **If a caller declines to answer** ("I'd rather not say"), don't press.
   Move on and leave that field null — a partial qualification is still
   useful (Qualification Capture Rate target is >80% of fields, not 100%
   of calls).
5. **Ambiguous answers get one clarifying follow-up, not more**: "Looking
   for something cheap" → "Understood — what's your target price ceiling?"
   per test scenario 13. If still vague after that, move on.

## Relationship to Fair Housing (see `system_prompt.py`)

None of these questions ever touch demographic/steering territory. Budget
and Timeline are financial/logistical only. If a caller volunteers
something demographic while answering ("we want to be near other
[group]"), the Fair Housing redirect in the system prompt takes priority
over BANT extraction for that turn.
