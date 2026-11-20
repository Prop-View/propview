# Full-call pipeline load test

`locustfile.py` exercises the call path without a paid Gemini account. Each
simulated caller joins a LiveKit room, dispatches `propview-agent`, publishes
audio, and waits for agent audio. In local load mode the orchestrator uses a
deterministic fake Gemini session that issues a `search_properties` tool call;
the real Tool Router, Postgres, Redis, LiveKit, orchestrator, and audio
publishing path still run.

The measured response time is from starting a simulated call until the first
agent audio frame arrives. Locust runs each asyncio/LiveKit call in a spawned
subprocess because its gevent-based concurrency cannot safely share LiveKit's
native FFI event loop.

## Start the full stack

From the repository root, copy `.env.example` to `.env` and set a valid
Fernet `ENCRYPTION_KEY` if you plan to use encrypted tenant settings. The
other local defaults are for development only; never use them in a deployed
environment.

```bash
docker compose build
GEMINI_SESSION_MODE=fake \
ENVIRONMENT=load \
ENABLE_PREDICTIVE_BARGE_IN=false \
docker compose up --scale worker=10
```

The fake session is only permitted when both `GEMINI_SESSION_MODE=fake` and
`ENVIRONMENT=load` are set. It makes one real Tool Router request per call,
then returns a small synthetic audio frame. It does not call Gemini, Twilio,
or Google Calendar. Keep the fake mode out of production deployments.

## Run 50–200 concurrent calls

In another terminal, install the pinned Locust dependencies and run from
`tests/load`:

```bash
uv pip sync requirements.lock
locust -f locustfile.py --headless -u 50 -r 5 --run-time 5m --csv=results-50
locust -f locustfile.py --headless -u 200 -r 10 --run-time 10m --csv=results-200
```

For a local capacity test, start with roughly one worker per five calls
(`--scale worker=10` for 50 callers, `--scale worker=40` for 200) and adjust
based on CPU, memory, and observed queueing. Set
`LOAD_TEST_CALL_TIMEOUT_SECONDS` to change the per-call ceiling (default 60),
and `LOAD_TEST_TENANT_ID` to exercise a separately provisioned tenant.
The default test tenant is `default`; property search can validly return an
empty result set.

Do not treat laptop results as production capacity evidence. For a meaningful
50–200 call benchmark, run Locust on a separate load generator against the
deployment target, then record worker CPU/memory, call failures, and response
latency alongside the CSV output. A paid Gemini key is not needed for this
fake-session path; a real Gemini run is a separate integration test.

## Scope and known gaps

- The test drives inbound audio through the orchestrator and a real Tool
  Router request, then confirms an agent audio frame reaches the caller.
- The Gemini model itself is replaced by a deterministic fake, so this does
  not measure provider latency, model quality, or paid API quota.
- The fake call uses local load-test metadata instead of a SIP caller's
  registered phone number. Real SIP dispatch and tenant-number resolution
  still require the live telephony integration test.
- Run the 50–200 caller workload against a dedicated target before claiming
  production capacity.
