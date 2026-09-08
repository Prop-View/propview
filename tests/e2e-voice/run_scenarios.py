"""
PROP-604: runs the scenario matrix (scenarios.py) against a real Gemini
session + real Tool Router, reporting pass/fail per scenario.

Needs: a running Tool Router (`cd services/tool-router && uvicorn
main:app --port 8000`) with migrations applied, and a real
GEMINI_API_KEY (loaded from services/gemini-client/.env).

Run:
    python run_scenarios.py                  # all scenarios
    python run_scenarios.py 1_simple_inquiry  # one scenario, by name
"""

from __future__ import annotations

import asyncio
import sys
from pathlib import Path

from dotenv import load_dotenv

from harness import run_scenario
from scenarios import SCENARIOS

load_dotenv(Path(__file__).resolve().parent.parent.parent / "services" / "gemini-client" / ".env")


async def main() -> None:
    only = sys.argv[1] if len(sys.argv) > 1 else None
    scenarios = [s for s in SCENARIOS if only is None or s.name == only]
    if not scenarios:
        sys.exit(f"No scenario named {only!r}. Available: {[s.name for s in SCENARIOS]}")

    results = []
    for scenario in scenarios:
        print(f"\n=== {scenario.name} ===")
        try:
            passed, reason, _ = await run_scenario(scenario)
        except Exception as exc:
            passed, reason = False, f"EXCEPTION: {exc!r}"
        status = "PASS" if passed else "FAIL"
        print(f"  {status}: {reason}")
        results.append((scenario.name, passed, reason))

    print(f"\n{'=' * 60}")
    passed_count = sum(1 for _, p, _ in results if p)
    print(f"RESULT: {passed_count}/{len(results)} passed")
    for name, passed, reason in results:
        if not passed:
            print(f"  FAILED: {name} -- {reason}")

    sys.exit(0 if passed_count == len(results) else 1)


if __name__ == "__main__":
    asyncio.run(main())
