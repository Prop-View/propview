# Database Migrations

Owner: Aahil (Dev A)

PostgreSQL + pgvector schema for listings/knowledge base, the CRM tables
(contacts, leads, appointments, interactions), and the Row-Level Security
policies for multi-tenant isolation.

- **PROP-301** — Listings, projects, pgvector schema
- **PROP-401** — Contacts, leads, appointments, interactions schema
- **PROP-601** — Row-Level Security (RLS) for `tenant_id` isolation

Per the architecture reference, the Lead Engine (scoring/rules) and Session
Store (Redis) are kept as distinct stores rather than folded into these
CRM tables — see `../../docs/architecture.md`.
