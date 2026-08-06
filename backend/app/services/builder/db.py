"""Postgres persistence for builder projects (same schema as backend-1)."""

from __future__ import annotations

import logging
from typing import Any

import asyncpg

from app.config import get_settings
from app.services.builder.json_extract import ProjectFile

logger = logging.getLogger(__name__)

_pool: asyncpg.Pool | None = None


async def get_pool() -> asyncpg.Pool:
    global _pool
    if _pool is None:
        settings = get_settings()
        _pool = await asyncpg.create_pool(
            dsn=settings.database_url,
            min_size=2,
            max_size=10,
            command_timeout=60,
        )
    return _pool


async def close_builder_pool() -> None:
    global _pool
    if _pool:
        await _pool.close()
        _pool = None


async def init_builder_db() -> None:
    pool = await get_pool()
    async with pool.acquire() as conn:
        await conn.execute(
            """
            CREATE TABLE IF NOT EXISTS projects (
                id TEXT PRIMARY KEY,
                user_id TEXT NOT NULL,
                name TEXT NOT NULL,
                prompt TEXT NOT NULL,
                status TEXT NOT NULL DEFAULT 'queued',
                dev_port INTEGER,
                created_at TIMESTAMP WITH TIME ZONE DEFAULT NOW(),
                updated_at TIMESTAMP WITH TIME ZONE DEFAULT NOW()
            );
            CREATE INDEX IF NOT EXISTS idx_projects_user_id ON projects(user_id);

            CREATE TABLE IF NOT EXISTS project_files (
                id SERIAL PRIMARY KEY,
                project_id TEXT NOT NULL REFERENCES projects(id) ON DELETE CASCADE,
                file_path TEXT NOT NULL,
                content TEXT NOT NULL,
                created_at TIMESTAMP WITH TIME ZONE DEFAULT NOW(),
                UNIQUE(project_id, file_path)
            );
            CREATE INDEX IF NOT EXISTS idx_project_files_project_id ON project_files(project_id);
            """
        )
    logger.info("Builder database tables initialized")


async def create_project(id: str, user_id: str, name: str, prompt: str) -> None:
    pool = await get_pool()
    async with pool.acquire() as conn:
        await conn.execute(
            "INSERT INTO projects (id, user_id, name, prompt, status) VALUES ($1, $2, $3, $4, $5)",
            id,
            user_id,
            name,
            prompt,
            "queued",
        )


async def update_project_status(
    id: str,
    status: str,
    dev_port: int | None = None,
    *,
    clear_dev_port: bool = False,
) -> None:
    pool = await get_pool()
    async with pool.acquire() as conn:
        if clear_dev_port:
            await conn.execute(
                "UPDATE projects SET status = $1, dev_port = NULL, updated_at = NOW() WHERE id = $2",
                status,
                id,
            )
        elif dev_port is not None:
            await conn.execute(
                "UPDATE projects SET status = $1, dev_port = $2, updated_at = NOW() WHERE id = $3",
                status,
                dev_port,
                id,
            )
        else:
            await conn.execute(
                "UPDATE projects SET status = $1, updated_at = NOW() WHERE id = $2",
                status,
                id,
            )


async def get_projects_by_user(user_id: str) -> list[dict[str, Any]]:
    pool = await get_pool()
    async with pool.acquire() as conn:
        rows = await conn.fetch(
            """
            SELECT id, name, status, prompt, dev_port, created_at, updated_at
            FROM projects WHERE user_id = $1 ORDER BY created_at DESC
            """,
            user_id,
        )
    return [dict(r) for r in rows]


async def get_project_by_id_and_user(id: str, user_id: str) -> dict[str, Any] | None:
    pool = await get_pool()
    async with pool.acquire() as conn:
        row = await conn.fetchrow(
            "SELECT * FROM projects WHERE id = $1 AND user_id = $2", id, user_id
        )
    return dict(row) if row else None


async def save_project_files(project_id: str, files: list[ProjectFile]) -> None:
    pool = await get_pool()
    async with pool.acquire() as conn:
        async with conn.transaction():
            for f in files:
                await conn.execute(
                    """
                    INSERT INTO project_files (project_id, file_path, content)
                    VALUES ($1, $2, $3)
                    ON CONFLICT (project_id, file_path) DO UPDATE SET content = $3
                    """,
                    project_id,
                    f.path,
                    f.content,
                )


async def get_project_files(project_id: str) -> list[dict[str, str]]:
    pool = await get_pool()
    async with pool.acquire() as conn:
        rows = await conn.fetch(
            """
            SELECT file_path, content FROM project_files
            WHERE project_id = $1 ORDER BY file_path
            """,
            project_id,
        )
    return [{"file_path": r["file_path"], "content": r["content"]} for r in rows]


async def get_project_file_content(project_id: str, file_path: str) -> str | None:
    pool = await get_pool()
    async with pool.acquire() as conn:
        row = await conn.fetchrow(
            "SELECT content FROM project_files WHERE project_id = $1 AND file_path = $2",
            project_id,
            file_path,
        )
    return row["content"] if row else None


async def delete_project(project_id: str, user_id: str) -> bool:
    """Delete project row (CASCADE project_files). Returns True if a row was removed."""
    pool = await get_pool()
    async with pool.acquire() as conn:
        result = await conn.execute(
            "DELETE FROM projects WHERE id = $1 AND user_id = $2",
            project_id,
            user_id,
        )
    # asyncpg: "DELETE N"
    try:
        return int(result.split()[-1]) > 0
    except (ValueError, IndexError):
        return False
