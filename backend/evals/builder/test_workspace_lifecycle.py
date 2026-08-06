"""Unit tests for disposable workspace / live Vite budget helpers."""

from __future__ import annotations

import time
from pathlib import Path
from unittest.mock import MagicMock

import pytest

from app.config import get_settings
from app.services.builder import jobs as jobs_mod
from app.services.builder.jobs import Job
from app.services.builder import workspace_lifecycle as life


@pytest.fixture(autouse=True)
def _clean_jobs(tmp_path, monkeypatch):
    jobs_mod.jobs.clear()
    monkeypatch.setenv("WORKSPACE_DIR", str(tmp_path / "workspaces"))
    monkeypatch.setenv("BUILDER_MAX_LIVE_PREVIEWS", "1")
    monkeypatch.setenv("BUILDER_IDLE_EVICT_SECONDS", "60")
    get_settings.cache_clear()
    (tmp_path / "workspaces").mkdir(parents=True, exist_ok=True)
    yield
    jobs_mod.jobs.clear()
    get_settings.cache_clear()


def _fake_live(job_id: str, *, activity: float | None = None) -> Job:
    job = Job(id=job_id, user_id="u1", status="completed", prompt="p")
    job.dev_port = 5200
    job.dev_process = MagicMock()
    job.last_activity_at = activity if activity is not None else time.time()
    jobs_mod.jobs[job_id] = job
    path = Path(get_settings().workspace_dir) / job_id
    path.mkdir(parents=True, exist_ok=True)
    (path / "package.json").write_text("{}", encoding="utf-8")
    return job


def test_ensure_live_preview_slot_evicts_lru(monkeypatch):
    older = _fake_live("old", activity=time.time() - 1000)

    def fake_kill(pid: str) -> None:
        j = jobs_mod.jobs[pid]
        j.dev_process = None
        j.dev_port = None

    monkeypatch.setattr(life, "kill_dev_server_for_job", fake_kill)

    evicted = life.ensure_live_preview_slot("incoming")
    assert len(evicted) == 1
    assert evicted[0]["projectId"] == "old"
    assert older.dev_port is None
    assert not (Path(get_settings().workspace_dir) / "old").exists()


def test_ensure_live_preview_slot_keeps_self(monkeypatch):
    me = _fake_live("me", activity=time.time())

    def fake_kill(pid: str) -> None:
        j = jobs_mod.jobs[pid]
        j.dev_process = None
        j.dev_port = None

    monkeypatch.setattr(life, "kill_dev_server_for_job", fake_kill)

    evicted = life.ensure_live_preview_slot("me")
    assert evicted == []
    assert me.dev_port == 5200
    assert (Path(get_settings().workspace_dir) / "me").exists()


def test_evict_idle_workspaces(monkeypatch):
    stale = _fake_live("stale", activity=time.time() - 10_000)
    fresh = _fake_live("fresh", activity=time.time())

    def fake_kill(pid: str) -> None:
        j = jobs_mod.jobs[pid]
        j.dev_process = None
        j.dev_port = None

    monkeypatch.setattr(life, "kill_dev_server_for_job", fake_kill)

    evicted = life.evict_idle_workspaces()
    ids = {e["projectId"] for e in evicted}
    assert ids == {"stale"}
    assert stale.dev_port is None
    assert fresh.dev_port == 5200
    assert not (Path(get_settings().workspace_dir) / "stale").exists()


def test_remove_workspace_keeps_job_metadata(monkeypatch):
    job = _fake_live("p1")

    def fake_kill(pid: str) -> None:
        j = jobs_mod.jobs[pid]
        j.dev_process = None
        j.dev_port = None

    monkeypatch.setattr(life, "kill_dev_server_for_job", fake_kill)
    life.evict_workspace("p1", reason="manual")
    assert "p1" in jobs_mod.jobs
    assert job.dev_port is None
    assert not (Path(get_settings().workspace_dir) / "p1").exists()
