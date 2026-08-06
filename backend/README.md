# Kiwi AI Unified Backend

Single FastAPI server that replaces:

| Legacy | Port | Role |
|--------|------|------|
| `backend-1` (Node) | 4000 | AI App Builder + general chat |
| `backend-3` (FastAPI) | 8005 | arXiv Research RAG |
| `grow-mcp/backend` (Node) | 4001 | Finance + Groww MCP |

Default unified port: **8000**.

## Quick start

```bash
cd backend
python -m venv venv
source venv/bin/activate
pip install -r requirements.txt
cp .env.example .env   # fill GEMINI_API_KEY, DATABASE_URL, Clerk keys
uvicorn app.main:app --reload --port 8000
```

Docs: http://localhost:8000/docs  
HLD (interview): [`docs/HLD.md`](docs/HLD.md)

## Evals

Builder / finance cores are injectable (no HTTP required):

```bash
cd backend
PYTHONPATH=. pytest evals/ -q
```

## Frontend

Point all three former base URLs at `http://localhost:8000` (see root README).
