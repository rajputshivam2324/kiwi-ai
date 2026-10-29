# syntax=docker/dockerfile:1

# ── Stage 1: compile/install Python deps (build tools stay here) ─────────────
FROM python:3.11-slim AS python-deps

ENV PIP_NO_CACHE_DIR=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1

WORKDIR /app

RUN apt-get update \
    && apt-get install -y --no-install-recommends build-essential \
    && rm -rf /var/lib/apt/lists/*

COPY requirements.txt .
RUN pip install -r requirements.txt

# Cache tokenizer ranks at build time; runtime ingestion needs no download.
ENV TIKTOKEN_CACHE_DIR=/opt/tiktoken-cache
RUN python -c "import tiktoken; tiktoken.get_encoding('cl100k_base')"


# ── Stage 2: runtime (Node for builder previews, no gcc/build-essential) ───────
FROM python:3.11-slim AS runtime

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    ENVIRONMENT=production \
    FINANCE_ENABLED=false \
    API_HOST=0.0.0.0 \
    API_PORT=8000 \
    WORKSPACE_DIR=/app/workspaces

ENV TIKTOKEN_CACHE_DIR=/opt/tiktoken-cache

WORKDIR /app

# Node 20 — only runtime needs npm for live Vite previews
RUN apt-get update \
    && apt-get install -y --no-install-recommends \
        curl \
        ca-certificates \
        gnupg \
        tesseract-ocr \
        tesseract-ocr-eng \
    && mkdir -p /etc/apt/keyrings \
    && curl -fsSL https://deb.nodesource.com/gpgkey/nodesource-repo.gpg.key \
        | gpg --dearmor -o /etc/apt/keyrings/nodesource.gpg \
    && echo "deb [signed-by=/etc/apt/keyrings/nodesource.gpg] https://deb.nodesource.com/node_20.x nodistro main" \
        > /etc/apt/sources.list.d/nodesource.list \
    && apt-get update \
    && apt-get install -y --no-install-recommends nodejs \
    && apt-get purge -y gnupg \
    && apt-get autoremove -y \
    && rm -rf /var/lib/apt/lists/* /tmp/* /root/.cache

# Copy pre-built site-packages from deps stage (no rebuild on code-only changes)
COPY --from=python-deps /usr/local/lib/python3.11/site-packages \
    /usr/local/lib/python3.11/site-packages
COPY --from=python-deps /usr/local/bin /usr/local/bin
COPY --from=python-deps /opt/tiktoken-cache /opt/tiktoken-cache

# App code last — best layer cache for frequent deploys
COPY . .

RUN mkdir -p /app/workspaces /app/data/chroma_db

# Fail the image build if the runtime cannot load the app/PDF stack, the
# preloaded tokenizer, FTS5, or the OCR binary used for scanned documents.
RUN python -c "import app.main, pymupdf4llm, langfuse, tiktoken, sqlite3; tiktoken.get_encoding('cl100k_base'); sqlite3.connect(':memory:').execute('CREATE VIRTUAL TABLE chunks USING fts5(text)')" \
    && tesseract --version

EXPOSE 8000

CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000"]
