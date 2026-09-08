"""
PROP-605: Locust load test simulating concurrent WebRTC calls against a
real LiveKit server.

Not HTTP load, so this doesn't use Locust's default HTTPUser -- it
follows Locust's own documented pattern for load-testing a non-HTTP
protocol: a plain `User` subclass whose task does the real work itself
and manually reports timing/success into Locust's stats via
`environment.events.request.fire(...)`.

**Bridging asyncio into Locust's gevent model**: Locust's concurrency is
gevent-based greenlets; LiveKit's Python SDK (`livekit-api`/`rtc`) is
asyncio-only. Each simulated call runs in its own **subprocess**
(`multiprocessing.Process`), not a thread -- the greenlet blocks on
`process.join()` (gevent's monkey-patched `threading`/`os.waitpid`
machinery makes that block only the calling greenlet, not the whole
process), and the subprocess runs a completely ordinary, un-patched
`asyncio.run()`.

Two lighter approaches were tried first and both hit real, reproducible
failures worth recording -- this is a genuinely hard combination, not a
one-line fix:
1. **One shared event loop** across all concurrent calls: with 3
   concurrent calls all publishing 20ms audio frames on one loop, every
   call's ~4s audio-publish stretched past 19 seconds (confirmed via
   LiveKit's own connection/disconnect log timestamps) -- a 20s run
   recorded **zero** completed calls.
2. **One thread per call**, each running its own fresh event loop
   (`asyncio.new_event_loop()` + `run_until_complete()`, then also tried
   plain `asyncio.run()`): both raised `RuntimeError` from inside
   asyncio's own "is a loop already running" checks on 75-80% of calls
   -- `asyncio.run() cannot be called from a running event loop`, then
   `Cannot run the event loop while another loop is running`. Root
   cause: gevent's monkey-patching (`socket`/`select`, applied
   process-wide by Locust) isn't scoped to the greenlet or even the OS
   thread that installed it -- a genuinely separate OS *thread* in the
   same process still routes through gevent's patched primitives, so
   asyncio's selector loop gets confused regardless of which thread
   creates it. Only a genuinely separate **process** has its own
   unpatched socket/select modules.

Subprocess-per-call is heavier (real process spawn cost, not just a
thread), but it's what actually works reliably at this test's target
concurrency (tens of calls, not thousands).

**One more real failure this surfaced**: the plain `multiprocessing.Process(...)`
default start method still resolved to `fork()` here, and LiveKit's own
FFI runtime detects and refuses that outright --
`RuntimeError: livekit.rtc was used in a parent process before fork();
the native runtime cannot be used across fork()`, since `from livekit
import rtc` at module import time (in the parent) already starts a
native background thread `fork()`'s copy-on-write semantics can't safely
duplicate. Fixed by explicitly requesting the `spawn` context
(`multiprocessing.get_context("spawn")`) -- a real fresh interpreter
process that re-imports everything from scratch, never copying the
parent's already-initialized native FFI state.

Each simulated "call" mirrors
`../../services/orchestrator/tests/test_orchestrator_live.py`'s own
setup: two participants join a room (a synthetic "caller" publishing a
tone, and a stand-in "agent" -- this load-tests LiveKit's own room/media
plumbing under concurrency, not the orchestrator+Gemini pipeline sitting
on top of it, which has its own per-call API cost that doesn't belong in
a raw connection-capacity load test).
"""

from __future__ import annotations

import asyncio
import math
import multiprocessing
import struct
import time
import uuid

from livekit import api, rtc
from locust import User, between, events, task

LIVEKIT_URL = "ws://localhost:7880"
API_KEY = "devkey"
API_SECRET = "secret"
CALLER_RATE_HZ = 8000  # mimics a phone leg, same as test_orchestrator_live.py
TONE_SECONDS = 2.0

def _subprocess_entrypoint(error_queue: multiprocessing.Queue) -> None:
    """Runs in a fresh, un-monkey-patched Python process -- see the module
    docstring for why this needs to be a real process, not a thread."""
    try:
        asyncio.run(_simulate_one_call())
    except BaseException as exc:  # noqa: BLE001 -- reported back to the parent greenlet below
        error_queue.put(repr(exc))


_mp_context = multiprocessing.get_context("spawn")  # NOT fork() -- see module docstring


def _run_one_call_in_subprocess() -> None:
    """Blocks the calling greenlet (not the process -- gevent's
    monkey-patched `os.waitpid` makes `process.join()` cooperative) until
    the subprocess finishes; re-raises whatever it failed with, if
    anything."""
    error_queue = _mp_context.Queue()
    process = _mp_context.Process(target=_subprocess_entrypoint, args=(error_queue,))
    process.start()
    process.join()
    if not error_queue.empty():
        raise RuntimeError(error_queue.get())
    if process.exitcode != 0:
        raise RuntimeError(f"simulated-call subprocess exited with code {process.exitcode}")


def _make_token(room_name: str, identity: str) -> str:
    grants = api.VideoGrants(room_join=True, room=room_name, can_publish=True, can_subscribe=True)
    return api.AccessToken(API_KEY, API_SECRET).with_identity(identity).with_grants(grants).to_jwt()


def _synth_tone(seconds: float, rate: int, freq: int = 300) -> bytes:
    n = int(seconds * rate)
    samples = [int(3000 * math.sin(2 * math.pi * freq * i / rate)) for i in range(n)]
    return struct.pack(f"<{n}h", *samples)


async def _simulate_one_call() -> None:
    room_name = f"load-test-{uuid.uuid4().hex[:8]}"
    caller_room = rtc.Room()
    agent_room = rtc.Room()
    try:
        await caller_room.connect(LIVEKIT_URL, _make_token(room_name, "caller"))
        await agent_room.connect(LIVEKIT_URL, _make_token(room_name, "agent"))

        caller_source = rtc.AudioSource(sample_rate=CALLER_RATE_HZ, num_channels=1)
        caller_track = rtc.LocalAudioTrack.create_audio_track("caller-voice", caller_source)
        await caller_room.local_participant.publish_track(
            caller_track, rtc.TrackPublishOptions(source=rtc.TrackSource.SOURCE_MICROPHONE)
        )

        tone = _synth_tone(TONE_SECONDS, CALLER_RATE_HZ)
        frame_samples = CALLER_RATE_HZ * 20 // 1000  # 20ms frames
        for i in range(0, len(tone), frame_samples * 2):
            chunk = tone[i : i + frame_samples * 2]
            if len(chunk) < frame_samples * 2:
                break
            frame = rtc.AudioFrame(data=chunk, sample_rate=CALLER_RATE_HZ, num_channels=1, samples_per_channel=frame_samples)
            await caller_source.capture_frame(frame)
            await asyncio.sleep(0.02)
    finally:
        await caller_room.disconnect()
        await agent_room.disconnect()


class SimulatedCallUser(User):
    wait_time = between(1, 3)

    @task
    def simulate_call(self) -> None:
        started = time.monotonic()
        exception = None
        try:
            _run_one_call_in_subprocess()
        except Exception as exc:  # noqa: BLE001 -- must report to Locust either way
            exception = exc
        events.request.fire(
            request_type="LiveKit",
            name="simulated_call",
            response_time=(time.monotonic() - started) * 1000,
            response_length=0,
            exception=exception,
        )
