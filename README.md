# Kiwi AI

An AI workspace for generating React applications, researching academic literature, and continuing conversations with persistent memory.

[![Backend CI/CD](https://github.com/rajputshivam2324/kiwi-ai/actions/workflows/backend-ci-cd.yml/badge.svg)](https://github.com/rajputshivam2324/kiwi-ai/actions/workflows/backend-ci-cd.yml)

[Live application](https://kiwiai.shivamio.in) · [API documentation](https://api.kiwiai.shivamio.in/docs) · [Evaluation report](backend/docs/evals/postgres-memory-cache/REPORT.md) · [RAG and memory internals](backend/docs/RESEARCH_RAG.md)

[Architecture](#architecture) · [Local setup](#run-locally) · [Configuration](#configuration) · [Evaluations](#observability-and-evaluations) · [Deployment](#deployment-and-operations)

Kiwi AI combines a React interface with one FastAPI backend. Gemini powers generation and tool use; PostgreSQL stores project source, conversation memory, and research passages; Chroma supplies semantic retrieval. Langfuse traces the AI workflows and records scored experiments, while Prometheus and Grafana cover service metrics.

## Product workflows

| Mode | What it does | Availability |
| --- | --- | --- |
| **Builder** | Generates and edits multi-file React/Vite projects, verifies builds, and launches live previews alongside a Monaco editor | Deployed |
| **Research** | Searches arXiv, retrieves indexed evidence, and streams answers with source URLs and page context | Deployed |
| **Chat** | Streams general assistance with owned PostgreSQL conversations and bounded model context | Deployed |
| **Finance** | Routes market, screening, technical-analysis, and portfolio questions across five specialists using Groww MCP | Development only; unavailable when `ENVIRONMENT=production` |

## Architecture

```mermaid
flowchart TB
    UI["React + TypeScript + Vite<br/>Clerk sessions · Monaco · streamed responses"]
    API["FastAPI<br/>REST + Server-Sent Events"]
    Builder["Builder<br/>generate → validate → build → repair"]
    Research["Research<br/>arXiv tools + hybrid retrieval"]
    Chat["Chat<br/>bounded conversation memory"]
    Finance["Finance · development only<br/>specialist routing + MCP tool loop"]
    PG[("PostgreSQL<br/>projects · transcripts · summaries<br/>passages · revisions · cache registry")]
    Chroma[("Chroma<br/>embedding vectors")]
    Gemini["Gemini<br/>generation · embeddings · provider caching"]
    Preview["Disposable workspaces<br/>npm builds + Vite previews"]
    Groww["Groww MCP<br/>local OAuth connection"]
    LF["Langfuse<br/>traces + scored experiments"]
    Metrics["Prometheus + Grafana<br/>HTTP · retries · cache usage"]

    UI -->|HTTPS / SSE| API
    API --> Builder
    API --> Research
    API --> Chat
    API -.-> Finance
    Builder --> PG
    Builder --> Preview
    Research --> PG
    Research --> Chroma
    Chat --> PG
    API --> Gemini
    Finance -.-> Groww
    API -. traces .-> LF
    API --> Metrics
```

The deployed topology is a Vercel frontend and an EC2 backend behind Nginx. The backend owns long-lived streams and preview subprocesses, so it runs as a persistent container. Job coordination, rate limiting, and live preview state are process-local; the current design targets one backend instance.

### State and durability

| State | Storage | Lifecycle |
| --- | --- | --- |
| Generated project files and metadata | PostgreSQL | Durable; used to restore disposable workspaces |
| Conversations, messages, summaries, and turn leases | PostgreSQL | Scoped to the authenticated owner |
| Research chunks, parent passages, active revisions, and keyword index | PostgreSQL | Staged per ingestion run, then activated transactionally |
| Semantic embeddings | Chroma persistent volume | IDs link vectors to indexed passages |
| Explicit prompt-cache references | PostgreSQL | Hashes, provider IDs, expiry, and usage metadata |
| Explicit cached model input | Gemini | Provider-managed TTL |
| Preview processes and installed dependencies | Backend workspace disk | Evicted on idle timeout or preview-slot pressure |

## Engineering details

### Application generation with build feedback

The builder separates orchestration from injected model, filesystem, persistence, and preview adapters. Generated output is parsed into file records, written to a workspace, and saved to PostgreSQL. The pipeline runs `npm install` and `npm run build`; failures feed a bounded repair loop before preview startup.

The default preview budget is one live Vite server. Starting another preview evicts the least recently active preview, and idle workspaces expire after 900 seconds. Project source remains in PostgreSQL and can be hydrated again. A failed build returns its warning and leaves the preview unavailable.

Implementation: [builder pipeline](backend/app/services/builder/pipeline.py), [build verification](backend/app/services/builder/verify.py), [workspace lifecycle](backend/app/services/builder/workspace_lifecycle.py).

### PDF ingestion and hybrid retrieval

Ingestion is a separate operation from asking a research question:

```text
arXiv search → bounded PDF download → page-wise Markdown extraction / OCR
    → section-aware parent and child passages → PostgreSQL staging
    → batched Gemini embeddings → Chroma upsert → activate revision

question → Chroma semantic candidates + PostgreSQL full-text candidates
    → reciprocal rank fusion → parent deduplication + paper diversity
    → expand matched children into parent passages → bounded evidence context
    → Gemini answer + source metadata
```

- **Page-aware extraction:** PyMuPDF4LLM handles text layout and detected tables. Sampled font statistics are reused across pages, avoiding a full-document heading scan for each page. Repeated margin text is filtered, and page/section provenance is retained.
- **Bounded processing:** PDFs spool to temporary files; passages are staged in PostgreSQL and embedded in batches. Scanned pages use Tesseract when OCR is enabled. An unreadable required page produces an explicit ingestion error.
- **Failure-safe revisions:** An incomplete ingestion run stays invisible. Previously indexed evidence remains available if a replacement fails. Cleanup checks active revision state before removing vectors, including after an uncertain commit acknowledgement.
- **Hybrid ranking:** Chroma candidates and PostgreSQL GIN full-text candidates are combined through reciprocal rank fusion. PostgreSQL uses `ts_rank_cd`; this is native full-text ranking, not BM25.
- **Evidence assembly:** Several distinct passages from one paper can reach the model, with page references and a separate retrieval-context budget. Small matched children expand into larger parent passages.

A one-time reader imports the earlier SQLite sidecar into PostgreSQL while preserving vector IDs. New staging, passage storage, and keyword retrieval use PostgreSQL. A migration marker prevents a reset from re-importing retired sidecar data. Older flat chunks need re-ingestion to gain page/section provenance and parent expansion.

Implementation: [PDF pipeline](backend/app/services/research/pdf_pipeline.py), [PostgreSQL index](backend/app/services/research/document_index.py), [hybrid retriever](backend/app/services/research/vectorstore.py).

### Persistent memory with a bounded context

Research and general chat retain full transcripts in PostgreSQL. Model requests receive a rolling summary plus recent complete turns within a token budget. Compaction advances its cutoff only after a successful summary and a compare-and-swap update; it does not delete the original messages.

Owner checks apply to conversation reads, writes, deletes, and context assembly. A turn lease returns HTTP `409` for overlapping generations on the same conversation. Failed or cancelled streams release their lease without storing a partial answer as a completed response. An expired worker cannot overwrite a newer turn.

Summary failures fall back to the previous summary and newest bounded turns. At most three compaction batches run per request, keeping a large backlog from triggering an unbounded chain of model calls. Client-supplied system/tool roles are excluded from conversation history.

Implementation: [conversation memory](backend/app/services/memory.py).

### Provider prompt caching

Reusable instructions precede research evidence, conversation history, and the latest question. For explicit caching, the application selects the instruction/evidence prefix, hashes the exact model, content, tools, and account scope, then looks up its provider cache reference in PostgreSQL.

Transaction-scoped locks prevent duplicate cache creation across concurrent workers. Evidence caches are account-scoped; conversation history and summaries are excluded from application-managed explicit caches. Stale cache references fall back to the original prompt before any stream output is emitted. Prefixes below the configured threshold are not padded.

Gemini implicit caching can also reuse repeated prompt prefixes. Actual provider-reported cached-token counts are recorded in Langfuse and Prometheus; a registry lookup alone is not treated as a provider cache hit. In the recorded evaluation, explicit creation was rejected by the project's zero cache-storage quota, while the repeated request reported **2,030 cached tokens out of 2,973 input tokens** through implicit caching.

Implementation: [prompt cache](backend/app/services/prompt_cache.py). Evidence: [evaluation report](backend/docs/evals/postgres-memory-cache/REPORT.md).

## Run locally

### Requirements

- Python **3.11+**; the backend has been checked on Python 3.11 and 3.14.
- Node.js **22.12+**, or the supported Node 20.19+ line required by Vite 7.
- PostgreSQL; **PostgreSQL 16** is used in CI and the example below.
- A Gemini API key and a Clerk application with its JWKS URL configured.
- Docker for the optional local PostgreSQL and monitoring containers.
- Tesseract and language data for local OCR; the backend image includes English OCR support.

### 1. Clone and create the environment files

```bash
git clone https://github.com/rajputshivam2324/kiwi-ai.git
cd kiwi-ai

test -f backend/.env || cp backend/.env.example backend/.env
test -f frontend/.env || cp frontend/.env.example frontend/.env
```

### 2. Start PostgreSQL

Use an existing database or start a local development instance:

```bash
docker run --name kiwi-postgres \
  -e POSTGRES_USER=kiwi \
  -e POSTGRES_PASSWORD=kiwi_local_dev \
  -e POSTGRES_DB=kiwi_ai \
  -p 127.0.0.1:5432:5432 \
  -v kiwi_postgres_data:/var/lib/postgresql/data \
  -d postgres:16
```

Set these values in `backend/.env`, using your own API and Clerk values:

```dotenv
DATABASE_URL=postgresql://kiwi:kiwi_local_dev@localhost:5432/kiwi_ai
GEMINI_API_KEY=your_gemini_api_key
GEMINI_MODEL=gemini-2.5-flash
CLERK_JWKS_URL=https://your-clerk-domain/.well-known/jwks.json
CLERK_DEV_BYPASS=false
ENVIRONMENT=development
FINANCE_ENABLED=false
CORS_ORIGINS=http://localhost:5173
CHROMA_DB_PATH=./data/chroma
```

`./data/chroma` is a fresh writable local directory. The checkout's `backend/data/chroma_db` entry is a legacy symlink; do not use that symlink as a new installation's data directory. The deployed container uses its mounted `/app/data/chroma_db` directory instead.

The backend creates its tables and indexes on initialization. The database role needs permission to create and alter the application tables and indexes.

Set `frontend/.env`:

```dotenv
VITE_CLERK_PUBLISHABLE_KEY=your_clerk_publishable_key
VITE_API_URL=http://localhost:8000
VITE_PREVIEW_BASE_URL=http://localhost:5200
```

### 3. Start the backend

From the repository root:

```bash
python3.11 -m venv backend/venv
backend/venv/bin/python -m pip install -r backend/requirements.txt pytest
backend/venv/bin/python -c "import tiktoken; tiktoken.get_encoding('cl100k_base')"

cd backend
venv/bin/uvicorn app.main:app --reload --port 8000
```

The tokenizer command downloads its vocabulary once. Docker preloads it at build time. To extract scanned PDFs locally, install Tesseract and the configured language data, then set `RAG_OCR_ENABLED=true`.

### 4. Start the frontend

In another terminal, from the repository root:

```bash
cd frontend
npm ci
npm run dev
```

Open **http://localhost:5173** and sign in through Clerk. Local API documentation is at **http://localhost:8000/docs**. Use `GET /api/health` for process liveness and `GET /api/research/health` for research diagnostics; the latter also probes arXiv and can take longer.

Finance is optional. To exercise it locally, set `FINANCE_ENABLED=true` in the development environment and complete the Groww MCP OAuth flow. Setting that flag does not enable finance in a production environment.

## Configuration

The full reference is [backend/.env.example](backend/.env.example). Production settings are documented in [deploy/backend.env.example](deploy/backend.env.example); frontend settings are in [frontend/.env.example](frontend/.env.example).

| Setting | Default | Purpose |
| --- | --- | --- |
| `RAG_CHILD_TOKENS` / `RAG_CHILD_OVERLAP` | `350` / `50` | Embedding passage size and overlap |
| `RAG_PARENT_TOKENS` | `1200` | Larger evidence passages for generation |
| `RAG_EMBEDDING_BATCH_SIZE` | `32` | Bounded embedding and staging batches |
| `RAG_CANDIDATE_COUNT` | `30` | Candidate pool requested from each retrieval path |
| `RAG_CONTEXT_TOKENS` | `6000` | Retrieved-evidence context budget |
| `RAG_MAX_PDF_BYTES` / `RAG_MAX_PDF_PAGES` | `50 MiB` / `1000` | PDF ingestion limits |
| `RAG_OCR_ENABLED` | `false` | Enable OCR for pages requiring it |
| `MEMORY_CONTEXT_TOKENS` / `MEMORY_SUMMARY_TOKENS` | `4000` / `800` | Conversation context and summary budgets |
| `MEMORY_RECENT_MESSAGES` | `8` | Recent-message window retained during compaction |
| `MEMORY_COMPACTION_BATCH` / `MEMORY_MAX_COMPACTION_BATCHES` | `40` / `3` | Compaction work limits per request |
| `MEMORY_TURN_TIMEOUT_SECONDS` | `600` | Expiry for a generation's conversation lease |
| `PROMPT_CACHE_ENABLED` / `PROMPT_CACHE_TTL_SECONDS` | `true` / `600` | Explicit cache attempts and provider TTL |
| `PROMPT_CACHE_MIN_TOKENS` / `PROMPT_CACHE_MAX_TOKENS` | `1024` / `32000` | Local token estimates used to gate explicit cache attempts |
| `LANGFUSE_ENABLED` / `LANGFUSE_CAPTURE_CONTENT` | `false` / `false` | Enable tracing and separately opt into content capture |
| `POSTGRES_POOL_SIZE` | `4` | Shared synchronous RAG/memory/cache connection pool; builder has its own async pool |
| `BUILDER_MAX_FIX_ROUNDS` | `2` | Build-repair limit |
| `BUILDER_MAX_LIVE_PREVIEWS` / `BUILDER_IDLE_EVICT_SECONDS` | `1` / `900` | Preview capacity and idle eviction |

Token limits use `cl100k_base` as a local budget estimate, not Gemini's native tokenizer. Evidence and memory have separate budgets; these settings are not a total model-input limit. Changing an embedding model may require a new `COLLECTION_NAME` to avoid mixing vector spaces or dimensions.

## API examples

The route names are preserved by the unified backend. [OpenAPI](https://api.kiwiai.shivamio.in/docs) provides request and response schemas.

| Endpoint | Purpose | Authentication |
| --- | --- | --- |
| `POST /api/build/chat` | Create a generation job | Clerk |
| `POST /api/build/chat/{project_id}` | Modify an owned project | Clerk + owner check |
| `GET /api/build/{job_id}/stream` | Run the build and stream events | Optional token; see operating boundaries |
| `POST /api/chat/message` | General chat with durable conversation memory | Clerk |
| `POST /chat` / `POST /chat/stream` | Research answer, ordinary or streamed | Clerk + conversation owner check |
| `GET /conversations` | List owned research conversations | Clerk |
| `GET /conversations/{id}/messages` | Read an owned transcript | Clerk + owner check |
| `POST /ingest` | Index arXiv papers into the shared corpus | No route-level auth; restrict at ingress |
| `DELETE /reset` | Reset the research collection | No route-level auth; restrict at ingress |
| `GET /api/health` | Process liveness | Public |
| `GET /api/research/health` | arXiv and knowledge-base diagnostics | Public |
| `GET /metrics` | Prometheus metrics | Restrict according to deployment |

Ingest a small corpus on a local or restricted administrative endpoint:

```bash
curl -X POST http://localhost:8000/ingest \
  -H 'Content-Type: application/json' \
  -d '{"query":"retrieval augmented generation","max_results":3,"include_full_text":true}'
```

The response includes `status` (`success`, `partial`, or `failed`), `documents_added`, `arxiv_ids`, `skipped_arxiv_ids`, and per-paper `errors`. Unchanged documents are skipped by a fingerprint covering PDF content, metadata, embedding model, and chunk settings.

For authenticated requests, set `CLERK_SESSION_TOKEN` to a current token from your Clerk session:

```bash
curl -N http://localhost:8000/chat/stream \
  -H "Authorization: Bearer ${CLERK_SESSION_TOKEN}" \
  -H 'Content-Type: application/json' \
  -d '{"message":"Explain the indexed papers and cite the supporting sources."}'
```

The stream returns a `conversation_id` event. Send that ID as `conversation_id` on later turns to reuse server-side memory. General chat returns the same identifier as a `conversation_id` field in its SSE envelope.

## Observability and evaluations

Langfuse traces PDF processing, ingestion, embedding batches, retrieval candidates, tools, memory loading, provider-cache events, and model generation. Stream observations follow generator lifetime. Prompt and completion capture is disabled by default; operational counts and provider usage remain available.

Enable tracing with `LANGFUSE_ENABLED=true`, `LANGFUSE_PUBLIC_KEY`, `LANGFUSE_SECRET_KEY`, and your project's `LANGFUSE_BASE_URL`. Then verify the connection:

```bash
cd backend
venv/bin/python -m app.scripts.check_langfuse
```

Prometheus metrics are exposed at `/metrics`, including:

- `kiwi_gemini_attempts_total`, `kiwi_gemini_attempt_duration_seconds`, and `kiwi_gemini_retries_total`.
- `kiwi_prompt_cache_events_total` and `kiwi_prompt_cache_read_tokens_total`.

### Automated regression suite

Use a disposable database, separate from application data. For the local PostgreSQL container above, create a test database once:

```bash
docker exec kiwi-postgres createdb -U kiwi kiwi_test
```

Run from the repository root:

```bash
cd backend
TEST_DATABASE_URL=postgresql://kiwi:kiwi_local_dev@localhost:5432/kiwi_test \
  PYTHONDONTWRITEBYTECODE=1 venv/bin/python -m pytest evals -q -m 'not integration'
```

The suite uses real PostgreSQL and temporary Chroma stores with deterministic provider doubles. It covers layout extraction, token limits, hybrid retrieval, migrations, failed embedding batches, uncertain commit acknowledgements, owner isolation, memory compaction, cache concurrency/expiry, and streaming behavior. PostgreSQL-dependent tests require `TEST_DATABASE_URL`; external arXiv tests are marked `integration`.

### Scored Langfuse experiment

This command uses real Gemini calls and publishes synthetic fixtures and scores to the configured Langfuse project:

```bash
cd backend
DATABASE_URL=postgresql://kiwi:kiwi_local_dev@localhost:5432/kiwi_test \
  venv/bin/python -m app.scripts.evaluate_ai
```

The runner creates a uniquely named test corpus, removes its corpus and conversations afterward, writes outputs and trace IDs under `backend/docs/evals/postgres-memory-cache/`, and exits nonzero on failed scored checks. Evaluators are deterministic checks applied to real model outputs.

**Recorded verification — October 29, 2026:**

| Check | Result |
| --- | --- |
| Automated backend suite | **87 passed**, with 2 external integration tests excluded |
| Langfuse experiment | **9 synthetic cases, 29 scored checks passed** |
| Late-document retrieval | Expected evidence recovered from page 80 and cited |
| Memory compaction | Early detector/unit preferences retained; a later correction replaced the original target |
| Provider cache usage | Warm request reported **2,030 cached input tokens** |
| Frontend | TypeScript/Vite production build passed |
| Deployed smoke checks | PostgreSQL ingestion/retrieval, generation, conversation ownership, turn leases, and Langfuse connectivity passed |

See the [report](backend/docs/evals/postgres-memory-cache/REPORT.md) and [raw results](backend/docs/evals/postgres-memory-cache/results.json). These focused fixtures establish specific regression behaviors; they are not a broad answer-quality benchmark or a cost/latency benchmark.

## Deployment and operations

The deployed layout uses:

- **Vercel:** frontend build from `frontend/`, configured by [vercel.json](frontend/vercel.json).
- **EC2 + Docker:** one backend container with persistent Chroma and disposable workspace volumes.
- **Nginx:** separate API and preview origins, SSE buffering disabled, and WebSocket forwarding for Vite.
- **PostgreSQL:** an external durable database; neither included Compose stack provisions it.
- **Prometheus + Grafana:** service metrics and a provisioned Prometheus datasource.

For a local image build:

```bash
docker build -t kiwi-ai-backend ./backend
```

To start the backend and monitoring stack after preparing `backend/.env`:

```bash
docker compose -f docker-compose.observability.yml up --build -d
```

That stack runs the backend with `ENVIRONMENT=production`. Configure a container-reachable `DATABASE_URL`, real Clerk JWKS, and the appropriate CORS origins. A host database is not reachable through the container's `localhost`. Local Grafana is on port `3001`; Prometheus is on `9090`.

For EC2, [deploy/backend.env.example](deploy/backend.env.example), [deploy/webhook.env.example](deploy/webhook.env.example), and [deploy/docker-compose.ec2.yml](deploy/docker-compose.ec2.yml) define the runtime and deployment inputs. Application secrets live in `/opt/kiwi/backend.env`; webhook/registry settings live in `/opt/kiwi/webhook.env`. These runtime files stay outside Git and image layers.

### CI/CD

[Backend CI/CD](.github/workflows/backend-ci-cd.yml) handles backend, deployment, and workflow changes:

1. Pull requests run the regression suite on Python 3.11 against a PostgreSQL 16 service, with provider calls/tracing disabled and tokenizer vocabulary preloaded.
2. Pushes to `main` run the tests, build the backend image, and publish it to GHCR.
3. The workflow calls the EC2 webhook using `BACKEND_DEPLOY_WEBHOOK_URL` and `BACKEND_DEPLOY_WEBHOOK_SECRET`.
4. When `DEPLOY_REPO_URL` is configured, the webhook syncs host deployment assets before pulling the image and recreating the backend.

Frontend deployment is managed separately by the connected Vercel project. The backend image bundles English OCR and tokenizer data and checks runtime imports during its build.

### Operating boundaries

- **One backend instance:** jobs, rate limits, and preview ownership are process-local. Horizontal scaling needs shared coordination and a separate preview execution strategy.
- **Generated-code execution:** npm installs, build scripts, and Vite run inside the backend container. Workspace cleanup and subprocess limits do not provide a sandbox for untrusted code.
- **Route-specific authorization:** ingestion/reset and builder event streams do not enforce the same Clerk/owner checks as conversation and project CRUD routes. Restrict those routes and preview access at ingress for your deployment.
- **Prompt-level policies:** source-grounding and finance order-confirmation instructions guide model behavior; they are not complete programmatic citation validation or a trading authorization system. Finance remains development-only.
- **Request-bound ingestion:** bulk ingestion is not a durable background queue. Large imports need suitable request timeouts or a separate ingestion worker.
- **Data recovery:** back up PostgreSQL and the Chroma volume together. `/api/health` reports process liveness; verify dependency initialization and run an end-to-end check after deployment.

Operational references: [deploy webhook](backend/docs/ec2-auto-deploy-webhook.md), [preview reverse proxy](backend/docs/ec2-preview-nginx.md), [host bootstrap](deploy/scripts/bootstrap-ec2.sh).

## Repository map

```text
backend/
  app/
    routers/                  Builder, research, chat, and finance APIs
    services/
      builder/                Generation, build repair, persistence, previews
      research/               PDF parsing, PostgreSQL indexing, hybrid RAG
      finance/                Specialist routing and Groww MCP integration
      memory.py               Owned transcripts and bounded rolling summaries
      prompt_cache.py         Provider cache registry and usage tracking
      postgres.py             Shared synchronous PostgreSQL pool
      observability.py        Langfuse lifecycle and tracing helpers
      gemini_client.py        Shared streaming client and retry logic
    scripts/                  Langfuse connection check and scored experiment
  evals/                      Automated regression tests
  docs/                       Pipeline documentation and evaluation evidence
  monitoring/                 Prometheus configuration and Grafana provisioning
frontend/
  src/pages/                  Landing, authentication, chat, and builder UI
  src/components/             Editor, file tree, previews, response rendering
  src/lib/api.ts              API base URL and authentication headers
deploy/                       EC2 Compose, webhook, Nginx, and systemd assets
.github/workflows/            Backend testing, image publishing, deployment
```

## Development

Use a disposable database for tests, keep provider calls behind explicit evaluation commands, and attach a scored experiment when changing prompts, retrieval, or memory behavior. Check the frontend with `npm run build` and the backend with the regression command above. New ingestion changes should preserve revision visibility and migration behavior under failure.

## License

The project's existing license designation is **MIT**. The repository does not yet include a standalone `LICENSE` file.
