# Kiwi AI Platform

> A full-stack, multi-agent AI platform for software development, academic research, and live financial analysis.

Kiwi AI combines a modern React frontend with specialized backend services to deliver three advanced AI workflows:

- 🛠️ **AI App Builder** — Generate, edit, and preview complete applications.
- 📚 **Research Assistant** — Perform Retrieval-Augmented Generation (RAG) with academic citations.
- 📈 **Finance Agent** — Analyze portfolios and interact with Groww via MCP.

> **Model Update:** The platform now uses **Google Gemini** models instead of Kimi for code generation, reasoning, and financial analysis.

---

## 🏗️ Architecture Overview

> **Unified backend:** All three former services now run as one FastAPI app on port **8000**.  
> Interview HLD (Mermaid): [`HLD.md`](HLD.md) · [`backend/docs/HLD.md`](backend/docs/HLD.md)

```text
Frontend (React + Vite + Tailwind + Clerk)
        │
        └── Unified Backend (FastAPI :8000)
                ├── Builder module      → Gemini + workspaces + Postgres
                ├── Research module     → arXiv + ChromaDB + Gemini + Postgres
                └── Finance module      → Groww MCP + multi-agent Gemini loop
```

Legacy folders (`backend-1`, `backend-3`, `grow-mcp`) remain for reference; prefer `backend/`.

---

## ✨ Features

### 🛠️ AI Builder Mode
Generate complete projects from natural language prompts.

**Capabilities**
- Full-stack code generation
- Multi-file editing
- Project scaffolding
- Live preview with Vite dev server
- Monaco code editor integration

**Example Prompt**
```text
Build a SaaS landing page using React, Tailwind CSS, and Stripe checkout.
```

---

### 📚 Research Mode (RAG)
Search academic papers and generate citation-backed responses.

**Pipeline**
1. Search papers from arXiv
2. Download and parse PDFs
3. Chunk documents
4. Generate embeddings
5. Store vectors in ChromaDB
6. Retrieve relevant context
7. Generate cited answers

**Features**
- Mandatory citation enforcement
- Multi-stage retrieval
- Persistent vector storage

---

### 📈 Finance Mode
Connect to Groww via MCP for portfolio analysis and trading.

**Capabilities**
- Portfolio analysis
- Market insights
- Fund and stock screening
- Guarded order execution
- Agentic tool loop (up to 10 rounds)

**Example Questions**
- "How is my portfolio performing?"
- "Compare Nifty 50 vs S&P 500."
- "Should I rebalance my holdings?"

---

## 🧱 Tech Stack

### Frontend
- React 19
- Vite
- Tailwind CSS
- Clerk Authentication
- Monaco Editor
- Server-Sent Events (SSE)

### Backend Services

#### Builder Service (`backend-1`)
- Node.js
- Express 5
- Google Gemini
- Local filesystem project storage

#### Research Service (`backend-3`)
- Python
- FastAPI
- LangChain
- ChromaDB
- PostgreSQL
- arXiv API

#### Finance Service (`grow-mcp/backend`)
- Node.js
- Express
- Google Gemini
- Groww MCP
- OAuth 2.0

### Infrastructure
- PostgreSQL 16 (Docker)
- ChromaDB (SQLite)
- Workspace filesystem

---

## 📁 Repository Structure

```text
kiwi-ai/
├── HLD.md                    # Interview Mermaid HLD
├── backend/                  # ★ Unified FastAPI (Builder + Research + Finance)
│   ├── app/
│   ├── evals/                # Offline unit/evals (mock LLM / router)
│   └── docs/HLD.md
├── backend-1/                # Legacy Node builder (reference)
├── backend-3/                # Legacy FastAPI research (reference)
├── frontend/                 # React application
└── grow-mcp/                 # Legacy Node finance (reference)
```

---

## ⚙️ Prerequisites

Before running the project, install:

- Node.js 20+
- Python 3.11+
- Docker & Docker Compose
- PostgreSQL (if not using Docker)
- Google Gemini API key
- Clerk account
- Groww developer credentials (optional)

---

## 🔐 Environment Variables

Create `.env` files for each service.

### Frontend (`frontend/.env`)
```env
VITE_CLERK_PUBLISHABLE_KEY=your_clerk_publishable_key
```

Frontend API bases point at `http://localhost:8000` (unified backend).

### Unified Backend (`backend/.env`)
```env
API_PORT=8000
GEMINI_API_KEY=your_gemini_api_key
DATABASE_URL=postgresql://kiwi:kiwi_secret_2024@localhost:5432/kiwi_ai
CHROMA_DB_PATH=./data/chroma_db
CLERK_SECRET_KEY=your_clerk_secret_key
CLERK_JWKS_URL=https://your-clerk-domain/.well-known/jwks.json
MCP_USE_STUB_TOOLS=false
```

See `backend/.env.example` for the full list.
---

## 🐳 Running with Docker Compose

```bash
docker compose up --build
```

## Deployment split (recommended)

- Frontend (`frontend/`) → **Vercel** at `https://kiwiai.shivamio.in`
- Backend (`backend/`) → **AWS EC2** + Docker + Nginx  
  Full beginner guide: [`deploy/EC2_DEPLOYMENT.md`](deploy/EC2_DEPLOYMENT.md)

| Host | Role |
|------|------|
| `api.kiwiai.shivamio.in` | FastAPI API + deploy webhook |
| `preview.kiwiai.shivamio.in` | Live Vite preview |
| `grafana.kiwiai.shivamio.in` | Observability UI |

This starts:

- Frontend
- Builder Service
- Research Service
- Finance Service
- PostgreSQL

---

## ▶️ Running Services Individually

### Frontend
```bash
cd frontend
npm install
npm run dev
```

### Unified Backend (recommended)
```bash
cd backend
python -m venv venv
source venv/bin/activate   # Windows: venv\Scripts\activate
pip install -r requirements.txt
cp .env.example .env       # fill keys
uvicorn app.main:app --reload --port 8000
```

Legacy services (`backend-1`, `backend-3`, `grow-mcp`) remain as reference only.
---

## 🌐 Default Ports

| Service | Port |
|-------|-----:|
| Frontend | 5173 |
| **Unified Backend** | **8000** |
| PostgreSQL | 5432 |

Legacy ports (4000 / 4001 / 8005) only if you run the old services separately.
---

## 🔄 Application Flows

### Builder Flow
1. User submits a coding prompt.
2. Frontend sends request to Builder Service.
3. Builder Service calls Google Gemini.
4. Generated files are written to the workspace.
5. A Vite dev server launches for preview.
6. Results stream back to the frontend via SSE.

### Research Flow
1. User asks a research question.
2. Research Service searches arXiv.
3. PDFs are downloaded and parsed.
4. Embeddings are created and stored in ChromaDB.
5. Relevant chunks are retrieved.
6. Gemini generates a citation-backed answer.

### Finance Flow
1. User asks a portfolio or market question.
2. Finance Service routes tool requests.
3. Groww MCP fetches live market data.
4. Gemini reasons over the results.
5. Guarded actions are executed when approved.

---

## 🔐 Security Features

- Clerk authentication with JWT verification
- Route-level authorization
- OAuth 2.0 for Groww integration
- Guardrails for trade execution
- Citation validation in research responses

---

## 📚 Documentation

- [`HLD.md`](HLD.md) — Mermaid HLD for interviews (system context, builder pipeline, RAG, finance agents)
- [`backend/docs/HLD.md`](backend/docs/HLD.md) — same doc next to the unified server
- [`backend/README.md`](backend/README.md) — run / eval instructions

---

## 🗺️ Roadmap

- [ ] Multi-model support (Gemini, OpenAI, Claude)
- [ ] Collaborative workspaces
- [ ] Voice interface
- [ ] One-click cloud deployment
- [ ] Backtesting and portfolio simulation

---

## 🤝 Contributing

Contributions are welcome.

```bash
# Fork the repository
git checkout -b feature/amazing-feature

# Commit changes
git commit -m "feat: add amazing feature"

# Push to your branch
git push origin feature/amazing-feature
```

Then open a Pull Request.

---

## 📄 License

This project is licensed under the MIT License.

---

## 🙌 Acknowledgements

- Google Gemini
- Clerk
- FastAPI
- LangChain
- ChromaDB
- Groww MCP
- arXiv

---

## 📬 Contact

For questions, suggestions, or collaboration opportunities:

- Open an issue on GitHub
- Start a discussion in the repository

---

## ⭐ Support

If you find this project useful, please consider starring the repository.
