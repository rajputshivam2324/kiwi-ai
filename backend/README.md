# Kiwi AI Unified Backend

Single FastAPI server that replaces:

| Legacy | Port | Role |
|--------|------|------|
| `backend-1` (Node) | 4000 | AI App Builder + general chat |
| `backend-3` (FastAPI) | 8005 | arXiv Research RAG |
| `grow-mcp/backend` (Node) | 4001 | Finance + Groww MCP |

Default unified port: **8000**.

## Production notes

- Builder and Research are production-ready in this backend container.
- Finance depends on local Groww MCP OAuth behavior and is therefore **disabled in production by default**.
- In production, finance endpoints return a `coming_soon` response instead of attempting MCP startup.
- This backend is stateful (SSE + local workspaces + subprocess previews), so it should run on a VM/container platform (Render, Railway, ECS, Fly, etc.), **not Vercel serverless**.

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

## Docker

Build the backend image:

```bash
docker build -t kiwi-ai-backend ./backend
```

Run it:

```bash
docker run --rm -p 8000:8000 \
  -e DATABASE_URL=postgresql://... \
  -e GEMINI_API_KEY=... \
  -e CLERK_JWKS_URL=... \
  -e CORS_ORIGINS=https://your-frontend-domain.com \
  kiwi-ai-backend
```

The image defaults to:

- `ENVIRONMENT=production`
- `FINANCE_ENABLED=false`

If you need to override those explicitly:

```bash
-e ENVIRONMENT=production \
-e FINANCE_ENABLED=false
```

## Evals

Builder / finance cores are injectable (no HTTP required):

```bash
cd backend
PYTHONPATH=. pytest evals/ -q
```

## CI/CD

GitHub Actions workflow: `.github/workflows/backend-ci-cd.yml`

- Pull requests: run backend evals
- Push to `main`: run evals, build Docker image, publish to `ghcr.io/<owner>/kiwi-ai-backend`
- Optional deploy trigger: set repository secret `BACKEND_DEPLOY_WEBHOOK_URL`

## Observability (Prometheus + Grafana)

Metrics endpoint is exposed at:

- `GET /metrics`

Run backend + monitoring stack:

```bash
docker compose -f docker-compose.observability.yml up --build -d
```

Services:

- Backend: `http://localhost:8000`
- Prometheus: `http://localhost:9090`
- Grafana: `http://localhost:3001` (default `admin/admin`)

Prometheus scrape config:

- `backend/monitoring/prometheus.yml`

Grafana datasource provisioning:

- `backend/monitoring/grafana/provisioning/datasources/prometheus.yml`

### AI (Gemini) metrics

The backend also exports Gemini streaming metrics (from `app/services/gemini_client.py`):

- `kiwi_gemini_attempts_total{model,outcome="success|retry|failure"}`
- `kiwi_gemini_attempt_duration_seconds{model,outcome="success|retry|failure"}`
- `kiwi_gemini_retries_total{model}`

In Grafana:
- open **Explore** and search for `kiwi_gemini_`
- add panels for these series.

## Frontend

Point all three former base URLs at `http://localhost:8000` (see root README).
