"""Disposable disk workspaces + live Vite budget controls.

Postgres is the durable source of truth. Disk under workspaces/ is ephemeral:
hydrate on preview, evict on idle / slot pressure / project delete.
"""

from __future__ import annotations

import logging
import shutil
import time
from pathlib import Path

from app.config import get_settings
from app.services.builder.jobs import (
    Job,
    jobs,
    kill_dev_server_for_job,
    workspace_path,
)

logger = logging.getLogger(__name__)


def touch_activity(project_id: str) -> None:
    job = jobs.get(project_id)
    if job:
        job.last_activity_at = time.time()


def list_live_preview_ids() -> list[str]:
    return [
        jid
        for jid, job in jobs.items()
        if job.dev_process is not None and job.dev_port is not None
    ]


def remove_workspace_dir(project_id: str) -> bool:
    """Delete disposable on-disk workspace. Source in Postgres is untouched."""
    path = workspace_path(project_id)
    if not path.exists():
        return False
    try:
        shutil.rmtree(path, ignore_errors=False)
        logger.info("Removed workspace disk for %s", project_id)
        return True
    except Exception as e:
        logger.error("Failed to remove workspace %s: %s", project_id, e)
        shutil.rmtree(path, ignore_errors=True)
        return True


def evict_workspace(project_id: str, *, reason: str = "evict") -> dict:
    """Stop Vite and wipe disk for one project. Keeps DB + in-memory job metadata."""
    kill_dev_server_for_job(project_id)
    removed = remove_workspace_dir(project_id)
    job = jobs.get(project_id)
    if job:
        job.dev_process = None
        job.dev_port = None
        job.last_activity_at = time.time()
    logger.info("Evicted workspace %s (%s, disk_removed=%s)", project_id, reason, removed)
    return {"projectId": project_id, "reason": reason, "diskRemoved": removed}


def ensure_live_preview_slot(for_project_id: str) -> list[dict]:
    """
    Enforce BUILDER_MAX_LIVE_PREVIEWS.

    If starting/refreshing `for_project_id` would exceed the cap, evict the
    least-recently-active *other* live previews (LRU).
    """
    settings = get_settings()
    max_live = max(1, settings.builder_max_live_previews)
    live = list_live_preview_ids()

    # Already counted as live — no new slot needed
    others = [pid for pid in live if pid != for_project_id]
    # Slot taken by this project + others
    need_free = len(others) + 1 - max_live
    if need_free <= 0:
        return []

    others_sorted = sorted(
        others,
        key=lambda pid: (jobs[pid].last_activity_at or 0.0),
    )
    evicted: list[dict] = []
    for pid in others_sorted[:need_free]:
        evicted.append(evict_workspace(pid, reason="concurrency_limit"))
    return evicted


def evict_idle_workspaces() -> list[dict]:
    """Stop Vite + wipe disk for live previews idle longer than configured TTL."""
    settings = get_settings()
    ttl = max(60, settings.builder_idle_evict_seconds)
    now = time.time()
    evicted: list[dict] = []
    for pid in list_live_preview_ids():
        job = jobs[pid]
        last = job.last_activity_at or 0.0
        if now - last >= ttl:
            evicted.append(evict_workspace(pid, reason="idle_timeout"))
    return evicted


def orphan_workspace_dirs() -> list[Path]:
    """Workspace dirs on disk with no in-memory live process (candidates after crash)."""
    root = Path(get_settings().workspace_dir)
    if not root.exists():
        return []
    live = set(list_live_preview_ids())
    orphans: list[Path] = []
    for entry in root.iterdir():
        if entry.is_dir() and entry.name not in live:
            orphans.append(entry)
    return orphans


def ensure_job_stub(project_id: str, user_id: str, status: str, prompt: str) -> Job:
    job = jobs.get(project_id)
    if not job:
        job = Job(
            id=project_id,
            user_id=user_id,
            status=status,
            prompt=prompt,
        )
        jobs[project_id] = job
    touch_activity(project_id)
    return job
