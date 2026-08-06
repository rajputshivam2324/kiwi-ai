# Kiwi AI — High-Level Design (Interview Guide)

> One FastAPI backend serving three product modes: **Builder**, **Research**, and **Finance**.

---

## 1. System context (what exists)

```mermaid
flowchart TB
    User([User Browser])

    subgraph Frontend["Frontend — React + Vite + Clerk"]
        ChatUI[Chat Page]
        BuildUI[Builder Page]
        Auth[Clerk Auth]
    end

    subgraph Backend["Unified Backend — FastAPI :8000"]
        API[API Gateway / Routers]
        Builder[Builder Module]
        Research[Research Module]
        Finance[Finance Module]
        SharedLLM[Shared Gemini Client<br/>retry · backoff · rate-limit]
    end

    subgraph External["External Services"]
        Gemini[Google Gemini]
        Clerk[Clerk JWKS]
        PG[(PostgreSQL)]
        Chroma[(ChromaDB)]
        Arxiv[arXiv API]
        Groww[Groww MCP<br/>mcp-remote]
        Vite[Vite Preview<br/>per-project]
    end

    User --> Frontend
    Auth --> Clerk
    ChatUI --> API
    BuildUI --> API

    API --> Builder
    API --> Research
    API --> Finance
    Builder --> SharedLLM
    Research --> SharedLLM
    Finance --> SharedLLM
    SharedLLM --> Gemini

    Builder --> PG
    Builder --> Vite
    Research --> PG
    Research --> Chroma
    Research --> Arxiv
    Finance --> Groww
    API --> Clerk
```

---

## 2. Request routing (one port, three domains)

| Mode | Frontend base | Key endpoints |
|------|---------------|---------------|
| Builder + general chat | `http://localhost:8000` | `/api/build/*`, `/api/chat/message` |
| Research (arXiv RAG) | same | `/`, `/chat/stream`, `/conversations*` |
| Finance (Groww) | same | `/health`, `/api/chat`, `/api/tools` |

```mermaid
flowchart LR
    FE[Frontend] -->|SSE / REST| GW[FastAPI :8000]

    GW -->|/api/build/*| B[Builder Router]
    GW -->|/api/chat/message| C[General Chat]
    GW -->|/chat/stream<br/>/conversations| R[Research Router]
    GW -->|/api/chat<br/>/health| F[Finance Router]
```

---

## 3. Builder pipeline (eval-friendly)

Core logic is **not** tied to Express/SSE. Stages are pure + injectable adapters:

```mermaid
flowchart TD
    A[POST /api/build/chat] --> J[Create job + DB row]
    J --> S[GET /api/build/:id/stream SSE]
    S --> P[generate_project pipeline]

    subgraph Core["Eval core — no HTTP / FS required"]
        P1[build_prompts]
        P2[LLM call + retry]
        P3[extract_json_object]
        P4[parse_and_validate_files]
        P1 --> P2 --> P3 --> P4
    end

    P --> Core
    Core --> W[write_files adapter]
    W --> D[save_db adapter]
    D --> V[start_preview adapter]
    V --> Done[SSE complete + devPort]
```

**Interview talking point:**  
“I decoupled the agent/codegen loop into a pipeline with injected LLM, FS, DB, and preview adapters so I can run offline evals with a mocked LLM returning fixture JSON.”

---

## 4. Research RAG flow

```mermaid
sequenceDiagram
    participant U as User
    participant API as FastAPI
    participant T as Research Tools
    participant VS as ChromaDB
    participant LLM as Gemini

    U->>API: POST /chat/stream
    API->>T: analyze_query_for_tools (heuristic)
    T->>T: arXiv live search / PDF / compare
    API->>VS: similarity_search(k=3)
    API->>LLM: system prompt + tool results + KB context
    LLM-->>API: streamed answer + citations
    API-->>U: SSE content / sources / [DONE]
    API->>API: persist messages in Postgres
```

---

## 5. Finance multi-agent tool loop

```mermaid
flowchart TD
    M[POST /api/chat] --> R{Keyword Router}
    R -->|RSI/MACD| TA[Technical Analyst]
    R -->|my portfolio| PT[Portfolio Tracker]
    R -->|fundamentals| SS[Stock Screener]
    R -->|price/LTP| MA[Market Analyst]
    R -->|buy/sell / default| IA[Investment Advisor]

    TA & PT & SS & MA & IA --> Loop[Gemini tool loop ≤ 10 rounds]
    Loop --> MCP[Groww MCP tools]
    MCP --> Loop
    Loop --> SSE[SSE text overwrite + agent event]
```

**Resilience:** exponential backoff on 429/5xx, `Retry-After` honor, tool-round delay, tool-output truncation, request dedup (429 if duplicate in-flight), allowlist fallback to all tools if names drift.

---

## 6b. Builder workspace budget (live Vite)

```mermaid
flowchart LR
    PG[(Postgres source)] -->|hydrate| Disk[workspaces/id]
    Disk --> Vite[npm run dev]
    Vite -->|idle TTL / slot limit / delete| Evict[kill + rmtree]
    Evict -.->|source kept| PG
    Delete[DELETE /projects/id] --> Evict
    Delete --> PG
```

| Setting | Default | Effect |
|---------|---------|--------|
| `BUILDER_MAX_LIVE_PREVIEWS` | `1` | LRU-evict other live Vites before starting another |
| `BUILDER_IDLE_EVICT_SECONDS` | `900` | Stop Vite + wipe disk after idle (DB kept) |
| `BUILDER_IDLE_SWEEP_SECONDS` | `60` | Background sweep interval |

`DELETE /api/build/projects/{id}` removes Postgres rows **and** disk. `POST .../evict` frees disk only.

---

## 6. Cross-cutting concerns

```mermaid
flowchart LR
    Req[Request] --> RL[In-memory rate limiter]
    RL --> Auth{Clerk JWT?}
    Auth -->|builder/chat| OK[Handler]
    Auth -->|research/finance| OK
    OK --> GeminiRetry[Gemini client<br/>retry + backoff]
    GeminiRetry --> Upstream[Upstream APIs]
```

| Concern | Where |
|---------|--------|
| Rate limit | `deps/rate_limit.py` — sliding window per IP/token |
| Auth | Clerk JWT (`require_auth` / `optional_auth` for SSE `?token=`) |
| Retry / backoff | `services/gemini_client.py` shared by builder + finance |
| Fallback | Builder empty-response retry; finance allowlist→all tools; MCP SSE noise ignored |

---

## 7. Data stores

```mermaid
erDiagram
    projects ||--o{ project_files : has
    arxiv_conversations ||--o{ arxiv_messages : has

    projects {
        text id PK
        text user_id
        text status
        int dev_port
    }
    project_files {
        text project_id FK
        text file_path
        text content
    }
    arxiv_conversations {
        uuid id PK
        text user_id
        text title
    }
    arxiv_messages {
        uuid id PK
        uuid conversation_id FK
        text role
        jsonb sources
    }
```

ChromaDB holds arXiv chunk embeddings (`arxiv_papers` collection). Builder workspaces live on disk under `workspaces/`.

---

## 8. Repo layout (unified)

```text
backend/
├── app/
│   ├── main.py                 # lifespan, CORS, router mount
│   ├── config.py
│   ├── deps/                   # auth, rate_limit
│   ├── routers/                # builder | chat | research | finance
│   └── services/
│       ├── gemini_client.py    # shared retry client
│       ├── builder/            # pipeline (eval core) + jobs + db
│       ├── research/           # RAG agent, tools, chroma, pg
│       └── finance/            # agents, MCP, chat_loop
├── evals/                      # offline unit/eval tests
└── docs/HLD.md                 # this file
```

---

## 9. 60-second interview pitch

1. **Problem:** three Node/Python backends → ops friction, duplicated Gemini clients, three ports.  
2. **Solution:** one FastAPI process, domain routers, shared Gemini client with retries.  
3. **Builder:** codegen pipeline extracted for evals (mock LLM, assert JSON contract).  
4. **Research:** heuristic tools + Chroma RAG + mandatory arXiv citation URLs.  
5. **Finance:** keyword multi-agent router + MCP tool loop (max 10) with rate-limit resilience.  
6. **Frontend:** single `VITE_API_URL` (or hardcoded `:8000`) — path contracts unchanged.
