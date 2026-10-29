# Kiwi AI backend

The FastAPI service for application generation, research RAG, conversation memory, and the development-only Groww finance module. All routers share port **8000**.

Start with the [project README](../README.md#run-locally) for PostgreSQL, Clerk, and frontend setup. [RESEARCH_RAG.md](docs/RESEARCH_RAG.md) describes ingestion, migrations, memory, prompt caching, and evaluation behavior in detail.

## Run

From `backend/`, after preparing `.env`:

```bash
python3.11 -m venv venv
venv/bin/python -m pip install -r requirements.txt pytest
venv/bin/python -c "import tiktoken; tiktoken.get_encoding('cl100k_base')"
venv/bin/uvicorn app.main:app --reload --port 8000
```

Use a writable `CHROMA_DB_PATH`, such as `./data/chroma`, for a fresh checkout. The tracked `data/chroma_db` entry is a legacy symlink. Configure `DATABASE_URL`, `GEMINI_API_KEY`, and `CLERK_JWKS_URL` in `.env`; keep `CLERK_DEV_BYPASS=false` for verified authentication. Set `FINANCE_ENABLED=false` to run without the local Groww OAuth integration.

Configuration: [.env.example](.env.example). Production template: [deploy/backend.env.example](../deploy/backend.env.example).

## Service layout

| Component | Responsibility |
| --- | --- |
| `services/builder/` | Generated-file parsing, PostgreSQL project persistence, install/build verification, bounded repairs, preview lifecycle |
| `services/research/` | arXiv tools, page-aware PDF/OCR extraction, PostgreSQL passages and revisions, Chroma candidates, rank fusion |
| `services/memory.py` | Owner checks, durable transcripts, rolling summaries, token bounds, generation leases |
| `services/prompt_cache.py` | Gemini prefix-cache references, expiry, account scoping, fallback, measured cache usage |
| `services/postgres.py` | Bounded synchronous pool for RAG workers, memory, and cache metadata |
| `services/gemini_client.py` | Shared streaming model client, retry/backoff, usage collection |
| `services/observability.py` | Optional Langfuse initialization, nested observations, masking, shutdown |
| `services/finance/` | Specialist routing, MCP schema adaptation, bounded tool loop |

PostgreSQL holds relational application state. Chroma holds semantic vectors. Research indexing stages rows under an ingestion run and activates a revision only after embedding completes; failures retain earlier evidence. A one-time compatibility reader imports previous SQLite sidecars without changing vector IDs.

Builder persistence uses its own `asyncpg` pool. RAG, memory, and cache metadata share the configured `psycopg` pool. Their advisory locks are transaction-scoped for compatibility with transaction poolers.

## API and diagnostics

- Interactive schema: `http://localhost:8000/docs`.
- `GET /api/health`: process liveness and enabled modules.
- `GET /api/research/health`: arXiv and knowledge-base diagnostics; includes external calls.
- `GET /metrics`: Prometheus metrics.
- Builder routes: `/api/build/*`.
- General chat: `POST /api/chat/message`.
- Research: `POST /chat`, `POST /chat/stream`, `/conversations*`, `POST /ingest`.

Authentication coverage is route-specific. Consult the [API table and operating boundaries](../README.md#api-examples), particularly for ingestion/reset, builder event streams, and previews.

## Tests and scored experiments

Use a disposable PostgreSQL database. The following assumes the test database from the root setup guide exists:

```bash
TEST_DATABASE_URL=postgresql://kiwi:kiwi_local_dev@localhost:5432/kiwi_test \
  PYTHONDONTWRITEBYTECODE=1 venv/bin/python -m pytest evals -q -m 'not integration'
```

The suite uses deterministic provider doubles, real PostgreSQL, and temporary Chroma stores. Tests requiring the test database are skipped when `TEST_DATABASE_URL` is absent; external arXiv tests are marked `integration`. CI provisions PostgreSQL 16 and supplies the test DSN.

With Gemini and Langfuse credentials configured, publish a scored synthetic experiment:

```bash
DATABASE_URL=postgresql://kiwi:kiwi_local_dev@localhost:5432/kiwi_test \
  venv/bin/python -m app.scripts.evaluate_ai
```

This invokes real models, records deterministic evaluator scores in Langfuse, and writes a report under `docs/evals/postgres-memory-cache/`. It exits nonzero on failed scores. The [recorded evaluation](docs/evals/postgres-memory-cache/REPORT.md) includes the observed explicit-cache quota limitation and verified implicit-cache usage.

## Observability

Set `LANGFUSE_ENABLED=true` and the project's `LANGFUSE_*` credentials/base URL in `.env`. Content capture remains off unless `LANGFUSE_CAPTURE_CONTENT=true` is explicitly set.

```bash
venv/bin/python -m app.scripts.check_langfuse
```

Operational metrics include `kiwi_gemini_attempts_total`, `kiwi_gemini_attempt_duration_seconds`, `kiwi_gemini_retries_total`, `kiwi_prompt_cache_events_total`, and `kiwi_prompt_cache_read_tokens_total`.

## Container and deployment

Build from the repository root:

```bash
docker build -t kiwi-ai-backend ./backend
```

The image includes Node for generated-app builds/previews, English Tesseract data, and a preloaded tokenizer vocabulary. It defaults to `ENVIRONMENT=production` and `FINANCE_ENABLED=false`. PostgreSQL is external to both Compose stacks; configure a container-reachable DSN.

Persist Chroma data and back up PostgreSQL. Workspaces are disposable because project source is stored in PostgreSQL. The current service runs one instance with process-local jobs and preview coordination; generated-code subprocesses are not an isolation sandbox.

[Backend CI/CD](../.github/workflows/backend-ci-cd.yml) tests changes, publishes the image to GHCR on `main`, and invokes the EC2 webhook when deployment secrets are configured. Host setup, credential locations, and proxy behavior are covered in the [deployment guide](../README.md#deployment-and-operations).
