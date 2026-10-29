# Research RAG and Langfuse

The `/ingest`, `/chat`, and `/chat/stream` endpoints retain their existing paths.

## Ingestion

The ingestion pipeline downloads a PDF to a temporary file with a 50 MiB default
limit, then extracts every readable page as Markdown using PyMuPDF4LLM. The
parser retains multi-column reading order and table structure where detected.
It samples repeating headers/footers for removal and computes heading detection
once, avoiding a whole-document scan for each page.

Each page retains its one-based source page number and section path. Paragraph
and sentence boundaries guide splitting into parents of up to 1,200 tokens and
embedding children of up to 350 tokens with 50-token overlap. The local
`cl100k_base` tokenizer is a budget estimate; it is not Gemini's native tokenizer.
Embedding inputs also include the paper title and section. Exact child text is
kept separately as evidence.

PostgreSQL stages each paper under an isolated ingestion run. Embeddings are
upserted into Chroma in batches of at most 32. Only after all batches succeed
does a PostgreSQL transaction switch the active revision and parent passages.
Failed replacements leave the previous version searchable, and incomplete
vectors are excluded from retrieval. Successful replacements retire their old
vectors. A hash of the PDF, metadata, model, and chunk settings skips unchanged
papers on repeated ingestion.

PostgreSQL is authoritative for document revisions, chunks, parent passages,
keyword search, conversation memory, and cache registry metadata. Chroma retains
embeddings in the existing `backend_chroma` Docker volume. Back up both stores.
On startup, a one-time read-only importer migrates any previous SQLite sidecar
without changing vector IDs. A durable migration marker prevents an explicit
reset from resurrecting old sidecar data. SQLite is never used for new writes,
ingestion staging, summaries, or retrieval. Do not run old and new backend
versions against one collection concurrently during migration.

Scanned pages require `RAG_OCR_ENABLED=true`. The Docker image includes English
Tesseract. Local installs need Tesseract and the relevant language data; configure
`RAG_OCR_LANGUAGE` for other languages. A required OCR failure rejects that paper
with an explicit error rather than claiming the full PDF was indexed. Truly
blank separator pages are skipped. Complex equations, figures, and unusual
layouts still need document-specific evaluation.

## Retrieval and evidence

Retrieval overfetches up to 30 candidates from Chroma semantic search and a
PostgreSQL GIN full-text index ranked with `ts_rank_cd`, then combines their rank positions with
reciprocal rank fusion. Repeated children of a parent are removed, and results
are diversified across papers. Matching small children expand to their larger
parent passages for generation. Either retriever can continue if the other is
unavailable; no additional neural reranking model is required. PostgreSQL native ranking
is explicitly not described as BM25 and needs no database extension.

The answer prompt can retain several distinct passages from one paper, with
page and section provenance, within a 6,000-token local context budget. UI source
cards remain deduplicated by paper. Streaming responses use a thread-safe queue;
ingestion and synchronous generation run off the FastAPI event loop.

The standalone summary tool now samples pages throughout the whole paper,
including its ending, within a bounded context. It reports the pages supplied
and whether sampling was applied; it does not claim an exhaustive summary.

Existing chunks continue to support semantic search. **Re-ingest existing papers
to gain layout extraction, parent expansion, and PostgreSQL keyword retrieval.** Changing the
embedding model may require a new `COLLECTION_NAME` because vector dimensions
and vector spaces must agree.

```bash
curl -X POST http://localhost:8000/ingest \
  -H 'Content-Type: application/json' \
  -d '{"query":"retrieval augmented generation", "max_results":5, "include_full_text":true}'
```

Responses include `status` (`success`, `partial`, or `failed`),
`documents_added` (new child chunks), `arxiv_ids` (indexed papers),
`skipped_arxiv_ids` (unchanged papers), and per-paper `errors`. Abstract-only
indexing is explicit via `include_full_text=false`. Request batches are limited
to 50 papers. Ingestion remains request-bound; for sustained bulk jobs, run the
Python ingestion service from a separate worker with suitable request timeouts.

## Langfuse

Set these in `backend/.env` (or the deployed `backend.env`):

```dotenv
LANGFUSE_ENABLED=true
LANGFUSE_PUBLIC_KEY=pk-lf-...
LANGFUSE_SECRET_KEY=sk-lf-...
LANGFUSE_BASE_URL=https://cloud.langfuse.com
LANGFUSE_CAPTURE_CONTENT=false
LANGFUSE_SAMPLE_RATE=1.0
```

Use the base URL for your project region or self-hosted installation. This
integration uses Python SDK v5, which requires Langfuse platform v4. See the
[SDK compatibility documentation](https://langfuse.com/docs/observability/sdk/overview).

Research traces cover PDF download/extraction, per-paper indexing, embedding
batches, hybrid candidate retrieval, individual tools, and RAG requests.
LangChain callbacks capture generation timing, model usage, and provider errors
for regular and streaming Gemini calls. User/conversation identifiers propagate
to the request's observations. The SDK client initializes from the same settings
as the app and shuts down at application exit.

The shared Gemini OpenAI-compatible client used by general chat, Builder, and
Finance is also instrumented through Langfuse's official OpenAI integration.
Its retry loop retains a root stream span, with provider calls nested beneath it.

Content capture is disabled by default: prompts, completions, and arbitrary
metadata are masked while operational counts and public paper/chunk identifiers
remain visible. Set `LANGFUSE_CAPTURE_CONTENT=true` to inspect textual evidence
and model inputs/outputs. An unavailable collector does not fail RAG requests.

Verify authentication and submit a trace containing no document content:

```bash
cd backend
venv/bin/python -m app.scripts.check_langfuse
```

Look for `kiwi.integration-check` in your project's Langfuse traces. The
[LangChain integration](https://langfuse.com/integrations/frameworks/langchain)
documents the callback mechanism used here.

## Verification

```bash
cd backend
TEST_DATABASE_URL=postgresql://kiwi:kiwi_test@localhost:5432/kiwi_test \
PYTHONDONTWRITEBYTECODE=1 venv/bin/python -m pytest evals -q -m 'not integration'
```

Tests use generated PDFs, real temporary Chroma stores and a disposable PostgreSQL database, and deterministic
fake embeddings. They cover extraction, column order, margin cleanup, token
bounds, oversized PDFs, explicit scan errors, batching, idempotency, atomic
replacement, filters, retrieval fallback, inactive-vector isolation, context
budgets, SSE delivery, and tracing lifecycle/privacy. A unique fact on page 80
must be recoverable even when every dense embedding is identical. These checks
verify behavior; they do not establish answer-quality gains on your corpus.

GitHub Actions starts a PostgreSQL 16 service and runs the offline suite on
Python 3.11 with provider calls/tracing disabled and
preloads the tokenizer vocabulary. The image build installs the PDF/OCR runtime
and bundles the same vocabulary. Existing deployment secrets trigger the EC2
webhook after GHCR publishing; runtime Langfuse keys belong in
`/opt/kiwi/backend.env`, which is intentionally excluded from Git and images.
The production environment template is `deploy/backend.env.example`.

## Conversation memory and account isolation

Research and general chat use PostgreSQL-backed conversations, full transcripts,
and rolling summaries. Both require verified Clerk identity; a request body
cannot select a different account. Reads, deletes, and context loads check owner
identity. General chat and research sessions are separated by module. The
frontend sends authorization for research chat and conversation management.
Production fails closed when Clerk JWKS is not configured.

The default model history budget is 4,000 local tokens, including an up-to-800
-token summary and recent complete turns. Compaction runs incrementally over
bounded batches; previous summaries are updated only after successful generation
and a compare-and-swap of the cutoff. Original messages remain intact. A failed
summary retains the previous summary and falls back to the newest bounded turns.
Client-injected system/tool roles are excluded. Retrieved evidence has its own
budget; conversation memory is never promoted to system instructions.

At most three compaction batches run per request. If an older backlog remains,
it stays durable for later compaction while the current request uses the stored
summary and newest bounded turns, avoiding an unbounded number of model calls.

A PostgreSQL turn lease rejects overlapping generations on the same conversation
with HTTP 409. Expired workers cannot append an answer after a newer turn has
started. Failed/cancelled streams release the lease and never persist a partial
answer as a complete response. General-chat SSE returns `conversation_id`, which
the browser sends on subsequent turns.

## Prompt caching

`PROMPT_CACHE_ENABLED=true` enables Gemini explicit prefix caching when the prefix
meets configured model limits. Cache keys cover the exact model, instructions,
evidence, and tool declarations. PostgreSQL stores only hashes, provider resource
names, usage counts, and expiry timestamps. A transaction-scoped lock prevents
concurrent workers from creating duplicate caches. Evidence caches are scoped to
the authenticated account; raw conversation history, summaries, and generated
answers are excluded. TTL defaults to 600 seconds. Stale cache errors retry the
original request once, before any stream output is emitted.

System instructions precede request-specific evidence/history to support Gemini
implicit caching too. Actual `cache_read` token counts from generation metadata
are used to verify reuse. A registry hit is not evidence of billed cached tokens.
If explicit caching is unavailable or the database is down, generation continues
with the original messages. Short prefixes are never padded to meet a threshold.
The configured Gemini project's explicit cache-storage quota may be zero; the
implementation backs off and still benefits from provider implicit cache hits.

## Langfuse scored experiments

Run against a disposable PostgreSQL database and your configured Gemini/Langfuse
accounts (real provider calls; synthetic fixtures only):

```bash
cd backend
DATABASE_URL=postgresql://kiwi:kiwi_test@localhost:5432/kiwi_test \
  venv/bin/python -m app.scripts.evaluate_ai
```

This publishes a versioned synthetic dataset and experiment to Langfuse, scores
retrieval/page recall, grounded citations, insufficient evidence, resistance to
instructions embedded in evidence, long-term fact retention, user corrections,
account isolation, memory token bounds, and observed provider cache usage. The
runner removes its uniquely named document corpus and conversations afterward.
Results and trace IDs are written to `docs/evals/postgres-memory-cache/results.json`.
It exits nonzero on failed scores. These small regression fixtures establish
specific behaviors rather than a general answer-quality benchmark.
