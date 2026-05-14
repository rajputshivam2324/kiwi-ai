# Kiwi AI Platform

> A full-stack, multi-agent AI platform for software development, academic research, and live financial analysis.

Kiwi AI combines a modern React frontend with specialized backend services to deliver three advanced AI workflows:

- 🛠️ **AI App Builder** — Generate, edit, and preview complete applications.
- 📚 **Research Assistant** — Perform Retrieval-Augmented Generation (RAG) with academic citations.
- 📈 **Finance Agent** — Analyze portfolios and interact with Groww via MCP.

> **Model Update:** The platform now uses **Google Gemini** models instead of Kimi for code generation, reasoning, and financial analysis.

---

## 🏗️ Architecture Overview

```text
Frontend (React + Vite + Tailwind)
        │
        ├── Clerk Authentication
        │
        ├── Builder Service (Node.js + Express)
        │       ├── Google Gemini
        │       ├── Workspace Filesystem
        │       └── PostgreSQL
        │
        ├── Research Service (FastAPI + LangChain)
        │       ├── arXiv API
        │       ├── ChromaDB
        │       ├── PostgreSQL
        │       └── Google Gemini
        │
        └── Finance Service (Node.js + Express)
                ├── Groww MCP
                └── Google Gemini
```

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
├── backend-1/
│   └── src/                  # AI Builder service
├── backend-3/                # Research RAG service
├── frontend/                 # React application
├── grow-mcp/
│   └── backend/              # Finance service
├── docker-compose.yml
└── README.md
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
VITE_BUILDER_API_URL=http://localhost:4000
VITE_FINANCE_API_URL=http://localhost:4001
VITE_RESEARCH_API_URL=http://localhost:8005
```

### Builder Service (`backend-1/.env`)
```env
PORT=4000
GEMINI_API_KEY=your_gemini_api_key
DATABASE_URL=your_database_url
WORKSPACE_DIR=./workspaces
CLERK_SECRET_KEY=your_clerk_secret_key
```

### Research Service (`backend-3/.env`)
```env
PORT=8005
GEMINI_API_KEY=your_gemini_api_key
DATABASE_URL=postgresql://postgres:password@localhost:5432/kiwi_ai
CHROMA_DB_DIR=./chroma_db
```

### Finance Service (`grow-mcp/backend/.env`)
```env
PORT=4001
GEMINI_API_KEY=your_gemini_api_key
GROWW_CLIENT_ID=your_groww_client_id
GROWW_CLIENT_SECRET=your_groww_client_secret
GROWW_REDIRECT_URI=http://localhost:4001/callback
```

---

## 🐳 Running with Docker Compose

```bash
docker compose up --build
```

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

### Builder Service
```bash
cd backend-1
npm install
npm run dev
```

### Research Service
```bash
cd backend-3
python -m venv venv

# Linux/macOS
source venv/bin/activate

# Windows
# venv\Scripts\activate

pip install -r requirements.txt
uvicorn app.main:app --reload --port 8005
```

### Finance Service
```bash
cd grow-mcp/backend
npm install
npm run dev
```

---

## 🌐 Default Ports

| Service | Port |
|-------|-----:|
| Frontend | 5173 |
| Builder Service | 4000 |
| Finance Service | 4001 |
| Research Service | 8005 |
| PostgreSQL | 5432 |

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

- `arch.mmd` — Mermaid source for architecture diagram
- `kiwi-ai-architecture.png` — Rendered architecture image
- `system_design_hld.html` — Detailed high-level design document

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
