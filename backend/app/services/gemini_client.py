"""Shared Gemini OpenAI-compatible client with retry / exponential backoff."""

from __future__ import annotations

import asyncio
import logging
import random
import time
from typing import Any, AsyncIterator, Callable, Optional

from openai import APIError, AsyncOpenAI, OpenAI
from prometheus_client import Counter, Histogram

from app.config import get_settings

logger = logging.getLogger(__name__)

_sync_client: OpenAI | None = None
_async_client: AsyncOpenAI | None = None


# ── Prometheus metrics ──────────────────────────────────────────────────────
_GEMINI_ATTEMPTS_TOTAL = Counter(
    "kiwi_gemini_attempts_total",
    "Number of Gemini streaming attempts (including retries)",
    ["model", "outcome"],  # outcome: success|retry|failure
)
_GEMINI_ATTEMPT_DURATION_SECONDS = Histogram(
    "kiwi_gemini_attempt_duration_seconds",
    "Duration of a single Gemini streaming attempt",
    ["model", "outcome"],
)
_GEMINI_RETRIES_TOTAL = Counter(
    "kiwi_gemini_retries_total",
    "Number of Gemini retries scheduled",
    ["model"],
)


def get_api_key() -> str:
    settings = get_settings()
    if not settings.gemini_api_key:
        raise RuntimeError("GEMINI_API_KEY or GOOGLE_API_KEY is not set")
    return settings.gemini_api_key


def get_sync_client(timeout_ms: int | None = None) -> OpenAI:
    global _sync_client
    settings = get_settings()
    kwargs: dict[str, Any] = {
        "api_key": get_api_key(),
        "base_url": settings.gemini_base_url,
    }
    if timeout_ms is not None:
        kwargs["timeout"] = timeout_ms / 1000.0
        # Don't reuse singleton when custom timeout requested
        return OpenAI(**kwargs)
    if _sync_client is None:
        _sync_client = OpenAI(**kwargs)
    return _sync_client


def get_async_client(timeout_ms: int | None = None) -> AsyncOpenAI:
    global _async_client
    settings = get_settings()
    kwargs: dict[str, Any] = {
        "api_key": get_api_key(),
        "base_url": settings.gemini_base_url,
    }
    if timeout_ms is not None:
        kwargs["timeout"] = timeout_ms / 1000.0
        return AsyncOpenAI(**kwargs)
    if _async_client is None:
        _async_client = AsyncOpenAI(**kwargs)
    return _async_client


def is_retryable_error(err: BaseException) -> bool:
    if isinstance(err, APIError):
        if err.status_code in (429, 500, 502, 503):
            return True
    msg = str(err)
    return bool(
        __import__("re").search(
            r"\b429\b|rate limit|RESOURCE_EXHAUSTED|overloaded|unavailable",
            msg,
            __import__("re").I,
        )
    )


def parse_retry_after_ms(err: BaseException) -> int | None:
    if not isinstance(err, APIError) or not getattr(err, "headers", None):
        return None
    raw = err.headers.get("retry-after") if err.headers else None
    if not raw:
        return None
    try:
        sec = int(str(raw).strip())
        return max(0, sec) * 1000
    except ValueError:
        return None


def compute_backoff_ms(attempt: int, initial_ms: int, max_ms: int, err: BaseException | None = None) -> int:
    wait = min(max_ms, initial_ms * (2 ** attempt)) + random.randint(0, 500)
    if err is not None:
        ra = parse_retry_after_ms(err)
        if ra is not None:
            wait = max(wait, ra)
    return wait


async def stream_chat_with_retry(
    *,
    messages: list[dict[str, Any]],
    model: str | None = None,
    temperature: float = 0.6,
    top_p: float | None = None,
    max_tokens: int = 4096,
    tools: list[dict[str, Any]] | None = None,
    timeout_ms: int | None = None,
    max_retries: int | None = None,
    on_retry: Callable[[int, int, str], None] | None = None,
) -> AsyncIterator[Any]:
    """
    Create a streaming chat completion with exponential backoff on 429/5xx.
    Yields OpenAI-compatible chunk objects.
    """
    settings = get_settings()
    client = get_async_client(timeout_ms=timeout_ms)
    retries = max_retries if max_retries is not None else settings.gemini_max_retries
    model_name = model or settings.llm_model
    last_err: BaseException | None = None

    params: dict[str, Any] = {
        "model": model_name,
        "messages": messages,
        "temperature": temperature,
        "max_tokens": max_tokens,
        "stream": True,
    }
    if top_p is not None:
        params["top_p"] = top_p
    if tools:
        params["tools"] = tools

    for attempt in range(retries):
        attempt_start = time.monotonic()
        try:
            stream = await client.chat.completions.create(**params)
            async for chunk in stream:
                yield chunk
            _GEMINI_ATTEMPTS_TOTAL.labels(model=model_name, outcome="success").inc()
            _GEMINI_ATTEMPT_DURATION_SECONDS.labels(model=model_name, outcome="success").observe(
                time.monotonic() - attempt_start
            )
            return
        except Exception as err:
            last_err = err
            if not is_retryable_error(err) or attempt >= retries - 1:
                _GEMINI_ATTEMPTS_TOTAL.labels(model=model_name, outcome="failure").inc()
                _GEMINI_ATTEMPT_DURATION_SECONDS.labels(model=model_name, outcome="failure").observe(
                    time.monotonic() - attempt_start
                )
                raise
            wait_ms = compute_backoff_ms(
                attempt,
                settings.gemini_backoff_initial_ms,
                settings.gemini_backoff_max_ms,
                err,
            )
            status = getattr(err, "status_code", "unknown")

            _GEMINI_ATTEMPTS_TOTAL.labels(model=model_name, outcome="retry").inc()
            _GEMINI_RETRIES_TOTAL.labels(model=model_name).inc()
            _GEMINI_ATTEMPT_DURATION_SECONDS.labels(model=model_name, outcome="retry").observe(
                time.monotonic() - attempt_start
            )

            logger.warning(
                "Gemini transient error (%s); backoff %sms (retry %s/%s)",
                status,
                wait_ms,
                attempt + 2,
                retries,
            )
            if on_retry:
                on_retry(attempt + 1, wait_ms, str(status))
            await asyncio.sleep(wait_ms / 1000.0)

    raise last_err or RuntimeError("Gemini stream failed")


async def collect_stream_text(
    *,
    messages: list[dict[str, Any]],
    model: str | None = None,
    temperature: float = 0.6,
    top_p: float | None = None,
    max_tokens: int = 4096,
    timeout_ms: int | None = None,
    max_retries: int | None = None,
    on_retry: Callable[[int, int, str], None] | None = None,
    on_chunk: Callable[[str], None] | None = None,
    include_reasoning: bool = False,
) -> str:
    """Collect full assistant text from a streaming call (skips reasoning by default)."""
    text = ""
    async for chunk in stream_chat_with_retry(
        messages=messages,
        model=model,
        temperature=temperature,
        top_p=top_p,
        max_tokens=max_tokens,
        timeout_ms=timeout_ms,
        max_retries=max_retries,
        on_retry=on_retry,
    ):
        delta = chunk.choices[0].delta if chunk.choices else None
        if not delta:
            continue
        content = getattr(delta, "content", None)
        if content:
            text += content
            if on_chunk:
                on_chunk(content)
        if include_reasoning:
            reasoning = getattr(delta, "reasoning_content", None)
            if reasoning and on_chunk:
                on_chunk(reasoning)
    return text
