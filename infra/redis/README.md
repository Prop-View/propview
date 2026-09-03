# Redis (Session Store)

Backs `services/orchestrator/session_store.py` (PROP-106) and, from
Sprint 2 on, the conversation-context truncation work (PROP-204).

## Local dev

```bash
brew install redis
brew services start redis   # or: redis-server
```

Defaults to `redis://localhost:6379`, matching
`services/orchestrator/.env.example`.

## Cloud deployment options

Not yet provisioned — pick one when deploying PROP-102's VM:

- **Simplest for Sprint 1 MVP**: run `redis-server` directly on the same
  cloud VM as LiveKit (`../livekit/`, `../gcp/`). One more service in that
  VM's `docker-compose.yml`; add `redis:7-alpine` alongside `livekit-server`
  and `livekit-sip`, and point `REDIS_URL` at it.
- **Production-appropriate**: a managed Redis service (AWS ElastiCache,
  Upstash, Redis Cloud) — avoids running stateful infra on a VM that
  Sprint 6's autoscaling/multi-tenancy work will eventually replace.

Whichever is chosen, `session_store.py` only needs a `REDIS_URL` — no
code changes required to switch between self-hosted and managed.
