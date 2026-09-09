"""
PROP-306/PROP-23: Real latency benchmark for tool execution + context
injection -- against real infra, not simulated. Two separate
measurements, since the plan's targets apply to different layers:

1. **Tool Router round trip alone** (HTTP -> DB query -> response), N
   repetitions -- isolates "including the DB query" (the plan's Sprint 3
   DoD: "<900ms... or masked with filler speech within 300ms", and the
   DB-specific mitigation: "enforce strict 350ms DB timeout").
2. **Full "user question -> agent starts speaking"**, via a real Gemini
   session: time from `send_text()` to the first `AudioChunk` after the
   tool round trip completes -- the plan's literal DoD wording for
   PROP-304 ("Total latency from user question to start of answer").

Run:
    # Tool Router already running (see tests/e2e-voice/README.md), a
    # real GEMINI_API_KEY loaded, and at least one property seeded for
    # tenant "test-latency-bench" (this file's default).
    python latency_benchmark.py
"""

from __future__ import annotations

import asyncio
import statistics
import sys
import time
from pathlib import Path

_SERVICES = Path(__file__).resolve().parent.parent.parent / "services"
sys.path.insert(0, str(_SERVICES / "gemini-client"))
sys.path.insert(0, str(_SERVICES / "prompts"))
sys.path.insert(0, str(_SERVICES / "orchestrator"))

from dotenv import load_dotenv

from gemini_live_client import AudioChunk, GeminiLiveSession, ToolCallRequest, TurnComplete  # noqa: E402
from orchestrator import build_gemini_tools  # noqa: E402
from system_prompt import build_system_prompt  # noqa: E402
from tool_client import ToolRouterClient  # noqa: E402

load_dotenv(_SERVICES / "gemini-client" / ".env")

TENANT_ID = "test-latency-bench"
TOOL_ROUTER_URL = "http://localhost:8000"
TOOL_ROUND_TRIP_ITERATIONS = 20
FULL_TURN_ITERATIONS = 5  # real Gemini calls -- kept modest, each costs real API time/money
TURN_TIMEOUT_SECONDS = 30


def _percentiles(samples_ms: list[float]) -> dict[str, float]:
    sorted_samples = sorted(samples_ms)
    return {
        "p50": statistics.median(sorted_samples),
        "p95": sorted_samples[min(int(len(sorted_samples) * 0.95), len(sorted_samples) - 1)],
        "min": sorted_samples[0],
        "max": sorted_samples[-1],
    }


async def benchmark_tool_round_trip() -> list[float]:
    """Pure Tool Router latency: HTTP request in, real Postgres query,
    response out. No Gemini involved -- isolates the DB-query component
    the plan's <900ms / 350ms-DB-timeout targets name explicitly."""
    tool_client = ToolRouterClient(base_url=TOOL_ROUTER_URL, tenant_id=TENANT_ID)
    samples_ms: list[float] = []
    try:
        for _ in range(TOOL_ROUND_TRIP_ITERATIONS):
            started = time.monotonic()
            await tool_client.call_tool("search_properties", {"city": "Austin"})
            samples_ms.append((time.monotonic() - started) * 1000)
    finally:
        await tool_client.aclose()
    return samples_ms


async def benchmark_full_turn_latency() -> list[float]:
    """"User question -> agent starts speaking," via a real Gemini
    session -- the plan's literal PROP-304 DoD wording. Measures
    send_text() to the first AudioChunk that arrives after the tool
    round trip completes (i.e. the real spoken answer, not any filler
    audio that might play during the wait)."""
    tool_client = ToolRouterClient(base_url=TOOL_ROUTER_URL, tenant_id=TENANT_ID)
    gemini_tools = build_gemini_tools(await tool_client.fetch_gemini_tools())
    samples_ms: list[float] = []

    try:
        for i in range(FULL_TURN_ITERATIONS):
            async with GeminiLiveSession(
                system_instruction=build_system_prompt("Austin Realty"), tools=gemini_tools
            ) as session:
                started = time.monotonic()
                await session.send_text(f"Do you have any houses in Austin under $600,000? (query {i})")

                tool_call_seen = False
                first_audio_after_tool_ms: float | None = None

                async def drive() -> None:
                    nonlocal tool_call_seen, first_audio_after_tool_ms
                    async for event in session.receive_events():
                        if isinstance(event, ToolCallRequest):
                            tool_call_seen = True
                            if event.name == "transfer_to_human_agent":
                                response = {"status": "transferred"}  # local-only tool, see harness.py
                            else:
                                try:
                                    result = await tool_client.call_tool(
                                        event.name, event.args, caller_phone_number="+15125559999"
                                    )
                                    response = {"result": result}
                                except Exception as exc:
                                    response = {"error": str(exc)}
                            await session.send_tool_response(call_id=event.id, name=event.name, response=response)
                        elif isinstance(event, AudioChunk) and tool_call_seen and first_audio_after_tool_ms is None:
                            first_audio_after_tool_ms = (time.monotonic() - started) * 1000
                        elif isinstance(event, TurnComplete):
                            return

                try:
                    await asyncio.wait_for(drive(), timeout=TURN_TIMEOUT_SECONDS)
                except TimeoutError:
                    print(f"  iteration {i}: timed out waiting for a response")
                    continue

                if first_audio_after_tool_ms is not None:
                    samples_ms.append(first_audio_after_tool_ms)
                    print(f"  iteration {i}: {first_audio_after_tool_ms:.0f}ms")
                else:
                    print(f"  iteration {i}: no tool call + audio response observed, skipped")
    finally:
        await tool_client.aclose()
    return samples_ms


async def main() -> None:
    print(f"=== Tool Router round-trip latency ({TOOL_ROUND_TRIP_ITERATIONS} calls, search_properties) ===")
    tool_samples = await benchmark_tool_round_trip()
    tool_stats = _percentiles(tool_samples)
    print(f"  p50={tool_stats['p50']:.1f}ms  p95={tool_stats['p95']:.1f}ms  min={tool_stats['min']:.1f}ms  max={tool_stats['max']:.1f}ms")
    print(f"  plan's 350ms DB-timeout mitigation: {'OK' if tool_stats['p95'] < 350 else 'EXCEEDS'} at p95")

    print(f"\n=== Full turn latency: question -> spoken answer ({FULL_TURN_ITERATIONS} real Gemini calls) ===")
    turn_samples = await benchmark_full_turn_latency()
    if turn_samples:
        turn_stats = _percentiles(turn_samples)
        print(f"  p50={turn_stats['p50']:.1f}ms  p95={turn_stats['p95']:.1f}ms  min={turn_stats['min']:.1f}ms  max={turn_stats['max']:.1f}ms")
        print(f"  plan's 900ms target: {'OK' if turn_stats['p95'] < 900 else 'EXCEEDS'} at p95")
    else:
        print("  no successful samples")


if __name__ == "__main__":
    asyncio.run(main())
