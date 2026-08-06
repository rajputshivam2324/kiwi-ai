"""In-memory job store + Vite preview subprocess management."""

from __future__ import annotations

import asyncio
import logging
import os
import signal
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from app.config import get_settings
from app.services.builder.json_extract import ProjectFile
from app.services.builder.verify import npm_install, wait_for_http

logger = logging.getLogger(__name__)


@dataclass
class Job:
    id: str
    user_id: str
    status: str  # queued | processing | completed | failed
    prompt: str
    result: dict[str, Any] | None = None
    error: str | None = None
    files: list[ProjectFile] | None = None
    existing_files: list[dict[str, str]] | None = None
    dev_port: int | None = None
    dev_process: asyncio.subprocess.Process | None = None
    last_activity_at: float = field(default_factory=time.time)


jobs: dict[str, Job] = {}
_next_dev_port: int | None = None
_idle_sweep_task: asyncio.Task | None = None


def allocate_port() -> int:
    global _next_dev_port
    settings = get_settings()

    # When we allow only one live preview at a time, keep Vite on a fixed port.
    # This makes it much easier to reverse-proxy previews on production.
    if settings.builder_max_live_previews <= 1:
        return settings.preview_port_start

    if _next_dev_port is None:
        _next_dev_port = settings.preview_port_start
    port = _next_dev_port
    _next_dev_port += 1
    return port


def generate_job_id() -> str:
    import random
    import time

    return f"job_{int(time.time() * 1000)}_{random.randrange(36**9):09x}"[:32]


def generate_project_name(prompt: str) -> str:
    words = " ".join(prompt.strip().split()[:6])
    return words[:50] + ("..." if len(words) > 50 else "")


def workspace_path(project_id: str) -> Path:
    return Path(get_settings().workspace_dir) / project_id


def ensure_workspaces_dir() -> Path:
    root = Path(get_settings().workspace_dir)
    root.mkdir(parents=True, exist_ok=True)
    return root


def write_files_to_disk(project_id: str, files: list[ProjectFile]) -> None:
    project_path = workspace_path(project_id)
    project_path.mkdir(parents=True, exist_ok=True)
    for f in files:
        file_path = project_path / f.path
        file_path.parent.mkdir(parents=True, exist_ok=True)
        file_path.write_text(f.content, encoding="utf-8")


def read_files_recursive(project_path: Path) -> list[dict[str, str]]:
    skip = {"node_modules", ".git", "package-lock.json", "yarn.lock", "dist", "build"}
    results: list[dict[str, str]] = []

    def walk(dir_path: Path, base: str = "") -> None:
        if not dir_path.exists():
            return
        for entry in dir_path.iterdir():
            if entry.name in skip:
                continue
            rel = f"{base}/{entry.name}" if base else entry.name
            if entry.is_dir():
                walk(entry, rel)
            else:
                try:
                    results.append({"path": rel, "content": entry.read_text(encoding="utf-8")})
                except Exception:
                    pass

    walk(project_path)
    return results


def get_file_structure(project_path: Path) -> list[dict[str, Any]]:
    skip = {"node_modules", ".git"}

    def walk(dir_path: Path) -> list[dict[str, Any]]:
        nodes: list[dict[str, Any]] = []
        if not dir_path.exists():
            return nodes
        for entry in sorted(dir_path.iterdir(), key=lambda p: p.name):
            if entry.name in skip:
                continue
            rel = str(entry.relative_to(project_path))
            if entry.is_dir():
                nodes.append(
                    {
                        "name": entry.name,
                        "type": "directory",
                        "path": rel,
                        "children": walk(entry),
                    }
                )
            else:
                nodes.append({"name": entry.name, "type": "file", "path": rel})
        return nodes

    return walk(project_path)


def kill_dev_server_for_job(job_id: str) -> None:
    job = jobs.get(job_id)
    if not job or not job.dev_process:
        return
    try:
        pid = job.dev_process.pid
        if pid:
            try:
                os.killpg(pid, signal.SIGTERM)
            except ProcessLookupError:
                job.dev_process.kill()
        job.dev_process = None
        job.dev_port = None
        logger.info("Killed existing dev server for job %s", job_id)
    except Exception as e:
        logger.error("Failed to kill dev server for %s: %s", job_id, e)


async def start_dev_server(
    job_id: str, project_path: Path, port: int
) -> tuple[asyncio.subprocess.Process, str]:
    """Start Vite dev server. Raises RuntimeError with logs on failure."""
    logger.info("Starting dev server for %s on port %s...", job_id, port)

    # Skip reinstall if verify step already ran npm install + build
    if not (project_path / "node_modules").exists():
        ok, install_log = await npm_install(project_path)
        if not ok:
            raise RuntimeError(install_log)

    proc = await asyncio.create_subprocess_shell(
        f"npm run dev -- --port {port} --host",
        cwd=str(project_path),
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
        start_new_session=True,
    )

    if proc.returncode is not None and proc.returncode != 0:
        err = (await proc.stderr.read()).decode(errors="replace") if proc.stderr else ""
        raise RuntimeError(f"Vite failed to start:\n{err}")

    ready = await wait_for_http(port, timeout=45.0)
    if not ready:
        if proc.returncode not in (None, 0):
            err = (await proc.stderr.read()).decode(errors="replace") if proc.stderr else ""
            raise RuntimeError(f"Dev server exited before ready:\n{err}")
        raise RuntimeError(
            f"Dev server on port {port} did not respond within 45s. "
            "Check generated code for runtime errors."
        )

    logger.info("Dev server ready for %s on port %s", job_id, port)
    return proc, ""


async def start_preview_for_job(job_id: str) -> int | None:
    from app.services.builder import db as builder_db
    from app.services.builder.workspace_lifecycle import (
        ensure_live_preview_slot,
        touch_activity,
    )

    job = jobs.get(job_id)
    project_path = workspace_path(job_id)
    if not project_path.exists():
        return None

    evicted = ensure_live_preview_slot(job_id)
    for item in evicted:
        pid = item.get("projectId")
        if not pid:
            continue
        other = jobs.get(pid)
        try:
            await builder_db.update_project_status(
                pid, other.status if other else "completed", clear_dev_port=True
            )
        except Exception:
            pass

    port = allocate_port()
    try:
        proc, _ = await start_dev_server(job_id, project_path, port)
        if job:
            job.dev_port = port
            job.dev_process = proc
            touch_activity(job_id)
        return port
    except Exception as e:
        logger.error("Preview start failed: %s", e)
        raise


def cleanup_all_dev_servers() -> int:
    killed = 0
    for job_id in list(jobs.keys()):
        if jobs[job_id].dev_process:
            kill_dev_server_for_job(job_id)
            killed += 1
    return killed


async def _idle_sweep_loop() -> None:
    from app.services.builder import db as builder_db
    from app.services.builder.workspace_lifecycle import evict_idle_workspaces

    settings = get_settings()
    interval = max(15, settings.builder_idle_sweep_seconds)
    logger.info(
        "Idle workspace sweeper started (every %ss, TTL %ss, max live %s)",
        interval,
        settings.builder_idle_evict_seconds,
        settings.builder_max_live_previews,
    )
    while True:
        try:
            await asyncio.sleep(interval)
            evicted = evict_idle_workspaces()
            for item in evicted:
                pid = item.get("projectId")
                if not pid:
                    continue
                job = jobs.get(pid)
                status = job.status if job else "completed"
                try:
                    await builder_db.update_project_status(
                        pid, status, clear_dev_port=True
                    )
                except Exception as e:
                    logger.warning("Failed to clear dev_port for %s: %s", pid, e)
            if evicted:
                logger.info("Idle sweep evicted %s workspace(s)", len(evicted))
        except asyncio.CancelledError:
            raise
        except Exception as e:
            logger.error("Idle sweep error: %s", e)


def start_idle_workspace_sweeper() -> None:
    global _idle_sweep_task
    if _idle_sweep_task and not _idle_sweep_task.done():
        return
    _idle_sweep_task = asyncio.create_task(_idle_sweep_loop())


async def stop_idle_workspace_sweeper() -> None:
    global _idle_sweep_task
    if not _idle_sweep_task:
        return
    _idle_sweep_task.cancel()
    try:
        await _idle_sweep_task
    except asyncio.CancelledError:
        pass
    _idle_sweep_task = None
