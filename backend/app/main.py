"""Kiwi AI — unified FastAPI backend (Builder + Research + Finance)."""

from __future__ import annotations

import asyncio
import logging
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from prometheus_fastapi_instrumentator import Instrumentator

from app.config import get_settings
from app.services.observability import get_langfuse, shutdown_langfuse
from app.routers import builder, chat, finance, research
from app.services.builder.db import close_builder_pool, init_builder_db
from app.services.builder.jobs import (
    cleanup_all_dev_servers,
    ensure_workspaces_dir,
    start_idle_workspace_sweeper,
    stop_idle_workspace_sweeper,
)
from app.services.finance.mcp_client import disconnect_mcp, get_mcp_client
from app.services.research.database import close_pool as close_research_pool
from app.services.research.database import init_db as init_research_db
from app.services.research.rag_agent import get_rag_agent
from app.services.research.vectorstore import get_vectorstore_service

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
)
logger = logging.getLogger(__name__)
settings = get_settings()


def _enabled_modules() -> list[str]:
    modules = ["builder", "research"]
    if settings.finance_available:
        modules.append("finance")
    return modules


@asynccontextmanager
async def lifespan(app: FastAPI):
    logger.info("Starting Kiwi AI unified backend")
    get_langfuse()
    logger.info("LLM model: %s", settings.llm_model)
    ensure_workspaces_dir()

    try:
        await init_builder_db()
        logger.info("Builder DB ready")
    except Exception as e:
        logger.error("Builder DB init failed: %s", e)

    try:
        await init_research_db()
        logger.info("Research DB ready")
    except Exception as e:
        logger.error("Research DB init failed: %s — conversations may be unavailable", e)

    try:
        vs = get_vectorstore_service()
        logger.info("ChromaDB docs: %s", vs.get_collection_count())
        get_rag_agent()
        logger.info("RAG agent ready")
    except Exception as e:
        logger.error("Research services init failed: %s", e)

    if settings.finance_available:
        # Groww MCP: connect in background so OAuth does not block HTTP startup
        mcp = get_mcp_client()
        mcp.start_background_connect()
        logger.info(
            "Groww MCP connect started in background (complete OAuth in browser if prompted)"
        )
    else:
        logger.info(
            "Finance MCP disabled for environment=%s; finance endpoints return coming soon",
            settings.app_env,
        )

    start_idle_workspace_sweeper()
    logger.info(
        "Builder live Vite budget: max=%s idle_evict=%ss",
        settings.builder_max_live_previews,
        settings.builder_idle_evict_seconds,
    )

    yield

    logger.info("Shutting down...")
    await stop_idle_workspace_sweeper()
    cleanup_all_dev_servers()
    if settings.finance_available:
        await disconnect_mcp()
    await close_builder_pool()
    await close_research_pool()
    await asyncio.to_thread(shutdown_langfuse)


app = FastAPI(
    title="Kiwi AI Unified Backend",
    description="Builder + Research RAG + Finance (Groww MCP) in one FastAPI service",
    version="3.0.0",
    lifespan=lifespan,
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.cors_origin_list or ["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Mount domain routers (path parity with legacy Node services)
app.include_router(builder.router)
app.include_router(chat.router)
app.include_router(finance.router)
app.include_router(research.router)

Instrumentator(
    should_group_status_codes=True,
    should_ignore_untemplated=True,
    excluded_handlers=["/metrics"],
).instrument(app).expose(app, include_in_schema=False)

# Static preview of generated workspaces
ws = Path(settings.workspace_dir)
ws.mkdir(parents=True, exist_ok=True)
app.mount("/preview", StaticFiles(directory=str(ws)), name="preview")


@app.get("/api/health")
async def unified_health():
    return {
        "status": "ok",
        "service": "kiwi-ai-unified",
        "version": "3.0.0",
        "modules": _enabled_modules(),
    }


if __name__ == "__main__":
    import uvicorn

    uvicorn.run(
        "app.main:app",
        host=settings.api_host,
        port=settings.api_port,
        reload=True,
    )
