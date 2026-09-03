# PROP-302: Listing Ingestion

Chunks property PDFs/text files and embeds them into `knowledge_base_chunks`
(PROP-301's pgvector table) for RAG retrieval.

## Setup

```bash
cd db/ingestion
pip install -r requirements.txt
```

Needs `GEMINI_API_KEY` (same key as `services/gemini-client/`) and
`DATABASE_URL` pointed at the `propview_app` role — RLS (PROP-601) means
inserts fail without the right tenant context set, which this script
handles itself.

## Usage

```bash
python ingest_listings.py <directory> --source-type faq [--project-id 1] [--property-id 1] [--tenant-id default]
```

Reads every `.txt`/`.md`/`.pdf` in `<directory>`, splits into ~500-char
chunks, embeds each with `gemini-embedding-001` at `output_dimensionality=768`
(its default is actually 3072 — verified directly, the model name in the
original schema comment, `text-embedding-004`, doesn't exist for this
account), and inserts them.

## Testing

```bash
GEMINI_API_KEY=... DATABASE_URL=postgresql://propview_app:devpassword@localhost/propview_dev python -m pytest tests/ -v
```

**Verified** 2026-09-03, real Gemini + real Postgres: 4/4 passing,
including the test that actually matters for RAG — a query with **no
words in common** with the source text ("How much are the monthly
homeowners association dues?" against a chunk saying "The HOA fee...")
still retrieves it correctly via semantic similarity (cosine distance
0.36), proving real embedding-based retrieval rather than lexical match.

## Definition of Done (from Sprint Plan)

- [x] Listing ingestion script (PDF/Text → chunks → embeddings).
- [x] Verified against real Postgres + real Gemini embeddings, including
      genuine semantic (not lexical) retrieval.
- [x] Wired into the Tool Router as `search_knowledge_base` — see
      `services/tool-router/tools/search_knowledge_base.py`. It must stay
      in sync with this script's `EMBEDDING_MODEL`/`EMBEDDING_DIMENSIONS`.
