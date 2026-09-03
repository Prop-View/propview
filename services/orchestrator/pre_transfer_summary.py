"""
PROP-504: Builds the pre-transfer context SMS sent to the human broker
before the call is bridged to them -- the plan's demo scenario: "dispatches
SMS context to Sarah, and bridges the call to her cell phone."

Pulled out as a pure function (no orchestrator/DB/network dependency) so
it's trivially unit-testable -- the actual data comes from what the
orchestrator already has in memory (no extra DB round trip): the most
recent update_lead_qualification result and the in-call transcript buffer.
"""

from __future__ import annotations

MAX_SMS_BODY_CHARS = 1500  # keep it well under typical carrier segment limits
MAX_RECENT_CALLER_LINES = 3


def build_pre_transfer_summary(
    caller_phone_number: str | None,
    reason: str | None,
    lead_snapshot: dict | None,
    transcript_lines: list[str],
) -> str:
    lines = [f"Incoming transfer -- caller: {caller_phone_number or 'unknown'}"]

    if reason:
        lines.append(f"Reason: {reason}")

    if lead_snapshot:
        parts = []
        if lead_snapshot.get("intent"):
            parts.append(f"intent={lead_snapshot['intent']}")
        budget_min, budget_max = lead_snapshot.get("budget_min"), lead_snapshot.get("budget_max")
        if budget_min is not None or budget_max is not None:
            parts.append(f"budget={budget_min or '?'}-{budget_max or '?'}")
        if lead_snapshot.get("timeline"):
            parts.append(f"timeline={lead_snapshot['timeline']}")
        if lead_snapshot.get("priority"):
            parts.append(f"priority={lead_snapshot['priority']}")
        if parts:
            lines.append("Lead: " + ", ".join(parts))

    recent_caller_lines = [line for line in transcript_lines if line.startswith("Caller:")][-MAX_RECENT_CALLER_LINES:]
    if recent_caller_lines:
        lines.append("Recent: " + " | ".join(recent_caller_lines))

    return "\n".join(lines)[:MAX_SMS_BODY_CHARS]
