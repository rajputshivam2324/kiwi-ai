"""Builder API routes — same paths as backend-1 for frontend parity."""

from __future__ import annotations

import io
import json
import logging
import zipfile
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import StreamingResponse

from app.deps.auth import optional_auth, require_auth
from app.deps.rate_limit import rate_limit_dependency
from app.services.builder import db as builder_db
from app.services.builder.jobs import (
    Job,
    cleanup_all_dev_servers,
    ensure_workspaces_dir,
    generate_job_id,
    generate_project_name,
    get_file_structure,
    jobs,
    kill_dev_server_for_job,
    read_files_recursive,
    start_dev_server,
    allocate_port,
    workspace_path,
    write_files_to_disk,
)
from app.services.builder.json_extract import ProjectFile
from app.services.builder.pipeline import PipelineAdapters, generate_project
from app.services.builder.workspace_lifecycle import (
    ensure_job_stub,
    ensure_live_preview_slot,
    evict_workspace,
    remove_workspace_dir,
    touch_activity,
)

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/api/build", tags=["builder"])


@router.post("/chat")
async def start_build(
    request: Request,
    user_id: str = Depends(require_auth),
    _: None = Depends(rate_limit_dependency),
):
    body = await request.json()
    prompt = body.get("prompt")
    if not prompt:
        raise HTTPException(400, detail="No Prompt received")

    job_id = generate_job_id()
    name = generate_project_name(prompt)
    try:
        await builder_db.create_project(job_id, user_id, name, prompt)
    except Exception as e:
        logger.error("Error creating job: %s", e)
        raise HTTPException(500, detail="Failed to create job") from e

    jobs[job_id] = Job(id=job_id, user_id=user_id, status="queued", prompt=prompt)
    return {"jobId": job_id, "status": "queued"}


@router.post("/chat/{project_id}")
async def follow_up_build(
    project_id: str,
    request: Request,
    user_id: str = Depends(require_auth),
    _: None = Depends(rate_limit_dependency),
):
    body = await request.json()
    prompt = body.get("prompt")
    if not prompt:
        raise HTTPException(400, detail="No Prompt received")

    project = await builder_db.get_project_by_id_and_user(project_id, user_id)
    if not project:
        raise HTTPException(404, detail="Project not found")

    # Follow-up rebuild: stop live Vite; keep disk for faster edit loop if present
    kill_dev_server_for_job(project_id)

    project_path = workspace_path(project_id)
    if project_path.exists():
        existing_files = read_files_recursive(project_path)
    else:
        db_files = await builder_db.get_project_files(project_id)
        existing_files = [
            {"path": f["file_path"], "content": f["content"]}
            for f in db_files
            if f["file_path"] not in ("package-lock.json", "yarn.lock")
        ]

    jobs[project_id] = Job(
        id=project_id,
        user_id=user_id,
        status="queued",
        prompt=prompt,
        existing_files=existing_files,
    )
    touch_activity(project_id)
    await builder_db.update_project_status(project_id, "queued")
    return {"jobId": project_id, "status": "queued", "isFollowUp": True}


@router.get("/{job_id}/stream")
async def build_stream(
    job_id: str,
    user_id: str | None = Depends(optional_auth),
):
    job = jobs.get(job_id)
    if not job:
        raise HTTPException(404, detail="Job not found")

    async def event_gen():
        import asyncio

        from app.services.builder.jobs import start_preview_for_job

        event_q: asyncio.Queue[tuple[str, dict[str, Any]] | None] = asyncio.Queue()

        def send_event(event: str, data: dict[str, Any]) -> None:
            event_q.put_nowait((event, data))

        send_event("status", {"step": "Starting build...", "progress": 0})
        job.status = "processing"
        try:
            await builder_db.update_project_status(job.id, "processing")
        except Exception:
            pass

        ensure_workspaces_dir()

        async def save_db(pid: str, files: list[ProjectFile]) -> None:
            await builder_db.save_project_files(pid, files)

        adapters = PipelineAdapters(
            write_files=write_files_to_disk,
            save_db=save_db,
            start_preview=start_preview_for_job,
        )

        async def run_pipeline():
            try:
                result = await generate_project(
                    project_id=job.id,
                    prompt=job.prompt,
                    existing_files=job.existing_files,
                    on_event=send_event,
                    adapters=adapters,
                )
                job.status = "completed"
                job.result = {"projectId": result.project_id}
                job.files = result.files
                job.dev_port = result.dev_port
                touch_activity(job.id)
                try:
                    await builder_db.update_project_status(
                        job.id, "completed", result.dev_port
                    )
                except Exception:
                    pass
                send_event(
                    "complete",
                    {
                        "projectId": job.id,
                        "devPort": result.dev_port,
                        "previewReady": result.preview_ready,
                        "buildWarning": result.build_warning,
                        "fixRounds": result.fix_rounds,
                    },
                )
            except Exception as err:
                logger.error("Job %s failed: %s", job_id, err)
                job.status = "failed"
                job.error = str(err)
                try:
                    await builder_db.update_project_status(job.id, "failed")
                except Exception:
                    pass
                send_event("error", {"message": str(err)})
            finally:
                event_q.put_nowait(None)

        task = asyncio.create_task(run_pipeline())
        try:
            while True:
                item = await event_q.get()
                if item is None:
                    break
                event, data = item
                yield f"event: {event}\ndata: {json.dumps(data)}\n\n"
        finally:
            await task

    return StreamingResponse(
        event_gen(),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "Connection": "keep-alive"},
    )


@router.get("/projects")
async def list_projects(user_id: str = Depends(require_auth)):
    try:
        projects = await builder_db.get_projects_by_user(user_id)
        out = []
        for p in projects:
            item = dict(p)
            for k in ("created_at", "updated_at"):
                if item.get(k) is not None:
                    item[k] = item[k].isoformat()
            out.append(item)
        return {"projects": out}
    except Exception as e:
        logger.error("Error fetching projects: %s", e)
        raise HTTPException(500, detail="Failed to fetch projects") from e


@router.get("/projects/{project_id}")
async def get_project(project_id: str, user_id: str = Depends(require_auth)):
    project = await builder_db.get_project_by_id_and_user(project_id, user_id)
    if not project:
        raise HTTPException(404, detail="Project not found")
    item = dict(project)
    for k in ("created_at", "updated_at"):
        if item.get(k) is not None:
            item[k] = item[k].isoformat()
    return {"project": item}


@router.delete("/projects/{project_id}")
async def delete_project(project_id: str, user_id: str = Depends(require_auth)):
    """Full delete: kill Vite, wipe disposable disk, remove Postgres rows."""
    project = await builder_db.get_project_by_id_and_user(project_id, user_id)
    if not project:
        raise HTTPException(404, detail="Project not found")

    kill_dev_server_for_job(project_id)
    disk_removed = remove_workspace_dir(project_id)
    deleted = await builder_db.delete_project(project_id, user_id)
    jobs.pop(project_id, None)

    if not deleted:
        raise HTTPException(404, detail="Project not found")

    return {
        "success": True,
        "projectId": project_id,
        "diskRemoved": disk_removed,
    }


@router.post("/projects/{project_id}/evict")
async def evict_project_workspace(
    project_id: str, user_id: str = Depends(require_auth)
):
    """Stop live Vite and wipe disk; keep project source in Postgres."""
    project = await builder_db.get_project_by_id_and_user(project_id, user_id)
    if not project:
        raise HTTPException(404, detail="Project not found")
    result = evict_workspace(project_id, reason="manual")
    await builder_db.update_project_status(
        project_id, project["status"], clear_dev_port=True
    )
    return {"success": True, **result}


@router.get("/status/{job_id}")
async def job_status(job_id: str, user_id: str = Depends(require_auth)):
    job = jobs.get(job_id)
    if job:
        touch_activity(job_id)
        return {
            "id": job.id,
            "status": job.status,
            "result": job.result,
            "error": job.error,
            "devPort": job.dev_port,
        }
    project = await builder_db.get_project_by_id_and_user(job_id, user_id)
    if project:
        return {
            "id": project["id"],
            "status": project["status"],
            "result": {"projectId": project["id"]}
            if project["status"] == "completed"
            else None,
            "devPort": project.get("dev_port"),
        }
    raise HTTPException(404, detail="Job not found")


@router.get("/files/{project_id}")
async def list_files(project_id: str, user_id: str = Depends(require_auth)):
    touch_activity(project_id)
    project_path = workspace_path(project_id)
    if project_path.exists():
        try:
            return {"files": get_file_structure(project_path)}
        except Exception as e:
            logger.error("Error reading files from fs: %s", e)

    db_files = await builder_db.get_project_files(project_id)
    if not db_files:
        raise HTTPException(404, detail="Project not found")

    root: list[dict[str, Any]] = []
    for file in db_files:
        parts = file["file_path"].split("/")
        current = root
        for i, part in enumerate(parts):
            is_file = i == len(parts) - 1
            path_so_far = "/".join(parts[: i + 1])
            existing = next((n for n in current if n["name"] == part), None)
            if not existing:
                existing = {
                    "name": part,
                    "type": "file" if is_file else "directory",
                    "path": path_so_far,
                    "children": None if is_file else [],
                }
                current.append(existing)
            if not is_file and existing.get("children") is not None:
                current = existing["children"]
    return {"files": root}


@router.get("/files/{project_id}/{file_path:path}")
async def get_file_content(
    project_id: str,
    file_path: str,
    user_id: str = Depends(require_auth),
):
    touch_activity(project_id)
    project_path = workspace_path(project_id)
    full_path = (project_path / file_path).resolve()
    if not str(full_path).startswith(str(project_path.resolve())):
        raise HTTPException(403, detail="Access denied")

    if full_path.exists():
        try:
            return {"content": full_path.read_text(encoding="utf-8")}
        except Exception:
            pass

    content = await builder_db.get_project_file_content(project_id, file_path)
    if content is not None:
        return {"content": content}
    raise HTTPException(404, detail="File not found")


@router.get("/download/{project_id}")
async def download_zip(project_id: str, user_id: str = Depends(require_auth)):
    project = await builder_db.get_project_by_id_and_user(project_id, user_id)
    if not project:
        raise HTTPException(404, detail="Project not found")

    project_path = workspace_path(project_id)
    if not project_path.exists():
        db_files = await builder_db.get_project_files(project_id)
        if not db_files:
            raise HTTPException(404, detail="Project files not found")
        write_files_to_disk(
            project_id,
            [ProjectFile(path=f["file_path"], content=f["content"]) for f in db_files],
        )

    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as zf:
        for path in project_path.rglob("*"):
            if path.is_file() and "node_modules" not in path.parts:
                zf.write(path, path.relative_to(project_path))
    buf.seek(0)
    return StreamingResponse(
        buf,
        media_type="application/zip",
        headers={
            "Content-Disposition": f'attachment; filename="{project_id}.zip"'
        },
    )


@router.post("/start-dev/{project_id}")
async def start_dev(project_id: str, user_id: str = Depends(require_auth)):
    project = await builder_db.get_project_by_id_and_user(project_id, user_id)
    if not project:
        raise HTTPException(404, detail="Project not found")

    ensure_job_stub(project_id, user_id, project["status"], project["prompt"])
    kill_dev_server_for_job(project_id)

    # Free a live slot (LRU-evict other previews) before install/start
    evicted = ensure_live_preview_slot(project_id)
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

    project_path = workspace_path(project_id)
    if not project_path.exists():
        db_files = await builder_db.get_project_files(project_id)
        if not db_files:
            raise HTTPException(404, detail="Project files not found")
        write_files_to_disk(
            project_id,
            [ProjectFile(path=f["file_path"], content=f["content"]) for f in db_files],
        )

    port = allocate_port()
    try:
        proc, _ = await start_dev_server(project_id, project_path, port)
        job = jobs[project_id]
        job.dev_port = port
        job.dev_process = proc
        touch_activity(project_id)
        await builder_db.update_project_status(project_id, project["status"], port)
        return {"port": port, "evicted": evicted}
    except Exception as e:
        logger.error("Error starting dev server: %s", e)
        raise HTTPException(500, detail=str(e) or "Failed to start dev server") from e


@router.delete("/jobs/{job_id}")
async def kill_job(job_id: str, user_id: str = Depends(require_auth)):
    """Stop Vite only (legacy). Prefer POST .../evict or DELETE .../projects/{id}."""
    job = jobs.get(job_id)
    if not job:
        project = await builder_db.get_project_by_id_and_user(job_id, user_id)
        if not project:
            raise HTTPException(404, detail="Job not found")
    kill_dev_server_for_job(job_id)
    return {"success": True}


@router.delete("/cleanup")
async def cleanup(user_id: str = Depends(require_auth)):
    killed = cleanup_all_dev_servers()
    return {"success": True, "killed": killed}
