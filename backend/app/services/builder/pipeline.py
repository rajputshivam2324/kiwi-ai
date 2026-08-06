"""
Builder generation pipeline — eval-friendly core.

HTTP / SSE / FS / DB / Vite are injected as adapters so unit/eval tests can
run prompts → LLM(mock) → extract → validate without side effects.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from typing import Any, Awaitable, Callable, Protocol

from app.config import get_settings
from app.services.builder.json_extract import ProjectFile, parse_and_validate_files
from app.services.builder.prompts import build_fix_prompt, build_prompts
from app.services.builder.verify import verify_project_build
from app.services.gemini_client import collect_stream_text

logger = logging.getLogger(__name__)

EventCallback = Callable[[str, dict[str, Any]], None]


class LLMFn(Protocol):
    async def __call__(
        self,
        system: str,
        user: str,
        *,
        on_retry: Callable[[int, int, str], None] | None = None,
        on_chunk: Callable[[str], None] | None = None,
    ) -> str: ...


@dataclass
class GenerateResult:
    project_id: str
    files: list[ProjectFile]
    dev_port: int | None = None
    preview_ready: bool = False
    build_warning: str | None = None
    fix_rounds: int = 0


@dataclass
class PipelineAdapters:
    """Optional side-effect adapters. Omit in evals."""

    write_files: Callable[[str, list[ProjectFile]], None] | None = None
    save_db: Callable[[str, list[ProjectFile]], Awaitable[None]] | None = None
    start_preview: Callable[[str], Awaitable[int | None]] | None = None
    llm: LLMFn | None = None


async def default_llm(
    system: str,
    user: str,
    *,
    on_retry: Callable[[int, int, str], None] | None = None,
    on_chunk: Callable[[str], None] | None = None,
) -> str:
    settings = get_settings()
    return await collect_stream_text(
        messages=[
            {"role": "system", "content": system},
            {"role": "user", "content": user},
        ],
        model=settings.llm_model,
        temperature=settings.builder_temperature,
        top_p=1.0,
        max_tokens=settings.builder_max_tokens,
        timeout_ms=120_000,
        max_retries=settings.builder_max_retries,
        on_retry=on_retry,
        on_chunk=on_chunk,
    )


async def generate_project(
    *,
    project_id: str,
    prompt: str,
    existing_files: list[dict[str, str]] | None = None,
    on_event: EventCallback | None = None,
    adapters: PipelineAdapters | None = None,
) -> GenerateResult:
    """
    Core builder stages (same as backend-1):
      prompts → LLM (retry) → extract JSON → validate → [write FS] → [save DB] → [preview]
    """
    adapters = adapters or PipelineAdapters()
    emit = on_event or (lambda _e, _d: None)

    system, user = build_prompts(prompt, existing_files)
    llm = adapters.llm or default_llm

    def _on_retry(attempt: int, wait_ms: int, status: str) -> None:
        emit(
            "status",
            {
                "step": f"API error ({status}), retrying in {wait_ms // 1000}s...",
                "progress": 15,
            },
        )

    chunk_count = 0

    def _on_chunk(_content: str) -> None:
        nonlocal chunk_count
        chunk_count += 1
        if chunk_count % 20 == 0:
            emit(
                "status",
                {
                    "step": "AI is generating code...",
                    "progress": 20 + min(25, chunk_count // 10),
                },
            )

    emit("status", {"step": "Generating code with AI...", "progress": 20})

    # Manual retry loop matching backend-1 (empty response also retries)
    settings = get_settings()
    response_text = ""
    last_error: Exception | None = None
    for attempt in range(1, settings.builder_max_retries + 1):
        try:
            if attempt > 1:
                emit(
                    "status",
                    {
                        "step": f"Retrying AI generation (attempt {attempt}/{settings.builder_max_retries})...",
                        "progress": 20,
                    },
                )
            response_text = await llm(
                system,
                user,
                on_retry=_on_retry,
                on_chunk=_on_chunk,
            )
            if response_text:
                last_error = None
                break
            raise ValueError("Empty response from API")
        except Exception as err:
            last_error = err
            logger.error(
                "Builder LLM attempt %s/%s failed: %s",
                attempt,
                settings.builder_max_retries,
                err,
            )
            if attempt < settings.builder_max_retries:
                import asyncio

                wait_ms = attempt * 5000
                emit(
                    "status",
                    {
                        "step": f"API error, retrying in {wait_ms // 1000}s...",
                        "progress": 15,
                    },
                )
                await asyncio.sleep(wait_ms / 1000.0)

    if last_error or not response_text:
        raise last_error or RuntimeError(
            "Failed to get response from AI after all retries"
        )

    return await _finalize_with_verify_and_preview(
        project_id=project_id,
        response_text=response_text,
        existing_files=existing_files,
        adapters=adapters,
        emit=emit,
        llm=llm,
    )


async def _finalize_with_verify_and_preview(
    *,
    project_id: str,
    response_text: str,
    existing_files: list[dict[str, str]] | None,
    adapters: PipelineAdapters,
    emit: EventCallback,
    llm: LLMFn,
) -> GenerateResult:
    from app.config import get_settings
    from app.services.builder.jobs import workspace_path

    settings = get_settings()
    max_fix_rounds = settings.builder_max_fix_rounds

    emit("status", {"step": "Parsing AI response...", "progress": 50})
    files = parse_and_validate_files(response_text)
    fix_rounds = 0
    last_error = ""

    project_path = workspace_path(project_id)

    if not adapters.write_files:
        files = parse_and_validate_files(response_text)
        return GenerateResult(project_id=project_id, files=files, preview_ready=False)

    while True:
        logger.info("Parsed %s files (fix round %s)", len(files), fix_rounds)

        emit("status", {"step": "Creating project files...", "progress": 70})
        if adapters.write_files:
            adapters.write_files(project_id, files)
        for f in files:
            emit("file", {"path": f.path, "content": f.content})

        emit("status", {"step": "Saving project to database...", "progress": 75})
        if adapters.save_db:
            try:
                await adapters.save_db(project_id, files)
            except Exception as e:
                logger.error("Failed to save files to database: %s", e)

        emit("status", {"step": "Verifying build (npm install + build)...", "progress": 82})
        ok, build_log = await verify_project_build(project_path)
        if ok:
            break

        last_error = build_log
        if fix_rounds >= max_fix_rounds:
            logger.error("Build still failing after %s fix rounds", fix_rounds)
            emit(
                "status",
                {
                    "step": "Build verification failed — preview unavailable",
                    "progress": 90,
                },
            )
            return GenerateResult(
                project_id=project_id,
                files=files,
                dev_port=None,
                preview_ready=False,
                build_warning=last_error,
                fix_rounds=fix_rounds,
            )

        fix_rounds += 1
        emit(
            "status",
            {
                "step": f"Build failed — auto-fixing with AI (attempt {fix_rounds}/{max_fix_rounds})...",
                "progress": 85,
            },
        )
        emit("build_error", {"message": last_error[:2000]})

        file_dicts = [{"path": f.path, "content": f.content} for f in files]
        sys_fix, user_fix = build_fix_prompt(last_error, file_dicts)
        response_text = await llm(sys_fix, user_fix)
        files = parse_and_validate_files(response_text)

    emit("status", {"step": "Starting preview server...", "progress": 92})
    dev_port: int | None = None
    preview_ready = False
    preview_error: str | None = None

    if adapters.start_preview:
        try:
            dev_port = await adapters.start_preview(project_id)
            if dev_port:
                preview_ready = True
                emit("status", {"step": "Preview ready!", "progress": 98})
        except Exception as e:
            preview_error = str(e)
            logger.error("Failed to start dev server: %s", e)
            emit(
                "status",
                {"step": "Preview server failed — code saved, try Restart Preview", "progress": 95},
            )

    emit("status", {"step": "Build complete!", "progress": 100})
    return GenerateResult(
        project_id=project_id,
        files=files,
        dev_port=dev_port,
        preview_ready=preview_ready,
        build_warning=preview_error,
        fix_rounds=fix_rounds,
    )
