# PROP-605: Load Testing

`locustfile.py` — Locust-driven concurrent LiveKit WebRTC session load
test, simulating the plan's "50 concurrent WebRTC calls" scenario.

## Why this isn't a standard Locust HTTPUser

LiveKit's Python SDK (`livekit-api`/`rtc`) is asyncio-only; Locust's own
concurrency is gevent-based greenlets. Each simulated call runs in its
own **subprocess** (`multiprocessing.get_context("spawn")`, explicitly —
not the default, see why below), and the greenlet blocks on
`process.join()` — gevent's monkey-patching of `threading`/`os.waitpid`
(applied automatically by Locust) makes that block only the calling
greenlet, not the whole process, so many simulated calls still run
concurrently.

This took three real, failed attempts to get right, each hitting a
genuine error rather than a hypothetical one — see `locustfile.py`'s
module docstring for the full blow-by-blow:
1. One shared event loop across all calls: severe contention, a 20s run
   recorded zero completed calls.
2. One thread per call, each with its own event loop: `RuntimeError`s
   from asyncio's own "is a loop already running" checks on 75-80% of
   calls — gevent's monkey-patching turned out to not be OS-thread-scoped.
3. `multiprocessing.Process` with the plain default start method: still
   resolved to `fork()`, which LiveKit's own FFI runtime explicitly
   refuses (`the native runtime cannot be used across fork()`) since
   `from livekit import rtc` already starts native background state in
   the parent at import time. Fixed by forcing the `spawn` context.

Each simulated "call" joins a room as two participants (a synthetic
caller publishing a tone + a stand-in agent), mirroring
`../../services/orchestrator/tests/test_orchestrator_live.py`'s own
setup — this load-tests LiveKit's own room/media plumbing under
concurrency, not the orchestrator+Gemini pipeline sitting on top of it
(which has its own real per-call API cost/rate limits that don't belong
in a raw connection-capacity test).

## Running it

```bash
# Needs a real LiveKit server -- livekit-server --dev (see
# ../../infra/livekit/LOCAL_TESTING.md)
cd tests/load
locust -f locustfile.py --headless -u 50 -r 5 --run-time 2m --csv=results
# or, for the interactive web UI:
locust -f locustfile.py
```

`-u 50` matches the plan's "simulate 50 concurrent WebRTC calls"; `-r 5`
ramps up 5 users/second rather than all 50 at once, closer to a real
traffic pattern than a instantaneous spike.

## Verification

**Verified working** 2026-09-08 at small scale (3 concurrent users, 20s,
against a local `livekit-server --dev`) — not the full 50-concurrent
scenario the plan specifies. Final result after the three fixes above:
**4 real simulated calls completed, 0 failures** (Locust's own
`--csv` stats output — median 7.5s response time, dominated by the
2s synthetic-audio publish loop plus real LiveKit connection overhead
for two participants per call). Low throughput at this small scale is
expected and not a finding — 3 concurrent users with a `between(1, 3)`
wait time were never going to produce many completed calls in 20s; the
result that matters here is 0 failures, confirming the subprocess
approach is actually reliable, not just "eventually stopped erroring."

**Not run at the plan's actual target scale (50 concurrent, sustained)**
in this environment — a single local dev machine running
`livekit-server --dev` isn't a realistic stand-in for whatever the real
deployment target's CPU/network capacity would be (the plan's own DoD is
about server resource usage under load, which a laptop's numbers
wouldn't represent meaningfully anyway). The script itself is real and
runnable; running it at real scale against a real deployment target is
the natural next step once PROP-102 is actually deployed.

## Definition of Done (from Sprint Plan)

- [x] Locust-driven concurrent LiveKit WebRTC session load test script.
- [x] Verified functional at small scale against a real LiveKit server.
- [ ] Run at the plan's actual target (50-200 concurrent) against a real
      deployment target, benchmarking CPU/RAM/TTFA degradation under load.
