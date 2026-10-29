"""Optional, fail-open Langfuse tracing shared by the research pipeline.

Never serialize service instances or entire PDFs. Content capture is opt-in;
the mask also applies to the LangChain callback's prompts and completions.
"""
from contextlib import contextmanager
from functools import lru_cache, wraps
import inspect
import logging

from app.config import get_settings

logger = logging.getLogger(__name__)


def _mask_content(*, data, **_):
    # Langfuse applies its mask to metadata as well as input/output. Preserve
    # operational attributes while suppressing arbitrary prompts and documents.
    safe = {"documents", "dimensions", "bytes", "sha256", "pages", "ocr_pages", "arxiv_id",
            "chunks_added", "skipped", "dense_candidates", "lexical_candidates", "selected",
            "chunk_ids", "tokens", "model", "ls_provider", "ls_model_name", "ls_model_type"}
    if isinstance(data, dict):
        return {key: value if key in safe else "[content capture disabled]" for key, value in data.items()}
    return "[content capture disabled]"


@lru_cache(maxsize=1)
def get_langfuse():
    settings = get_settings()
    if not settings.langfuse_enabled:
        return None
    if not (settings.langfuse_public_key and settings.langfuse_secret_key):
        logger.warning("Langfuse enabled but keys are missing; tracing disabled")
        return None
    try:
        from langfuse import Langfuse
        return Langfuse(
            public_key=settings.langfuse_public_key,
            secret_key=settings.langfuse_secret_key,
            base_url=settings.langfuse_base_url,
            environment=settings.app_env,
            sample_rate=settings.langfuse_sample_rate,
            mask=None if settings.langfuse_capture_content else _mask_content,
        )
    except Exception:
        logger.exception("Langfuse initialization failed; continuing without tracing")
        return None


class Observation:
    def __init__(self, span=None):
        self.span = span

    def update(self, **kwargs):
        if self.span is not None:
            try:
                self.span.update(**kwargs)
            except Exception:
                logger.warning("Langfuse update failed", exc_info=True)


@contextmanager
def observation(name, as_type="span", **kwargs):
    """SDK lifecycle failures must not mask application failures or rerun work."""
    client = get_langfuse()
    manager = None
    span = None
    if client is not None:
        try:
            manager = client.start_as_current_observation(name=name, as_type=as_type, **kwargs)
            span = manager.__enter__()
        except Exception:
            manager = None
            logger.warning("Langfuse span creation failed", exc_info=True)
    try:
        yield Observation(span)
    except BaseException as error:
        if manager is not None:
            try:
                manager.__exit__(type(error), error, error.__traceback__)
            except Exception:
                logger.warning("Langfuse span close failed", exc_info=True)
        raise
    else:
        if manager is not None:
            try:
                manager.__exit__(None, None, None)
            except Exception:
                logger.warning("Langfuse span close failed", exc_info=True)


def traced(name, as_type="span"):
    """Keep observations open for the full sync/async generator lifetime."""
    def decorate(function):
        if inspect.isasyncgenfunction(function):
            @wraps(function)
            async def async_generator(*args, **kwargs):
                with observation(name, as_type) as span:
                    stream = function(*args, **kwargs)
                    try:
                        async for item in stream:
                            _record_result(span, item)
                            yield item
                    finally:
                        await stream.aclose()
            return async_generator
        if inspect.iscoroutinefunction(function):
            @wraps(function)
            async def coroutine(*args, **kwargs):
                with observation(name, as_type) as span:
                    result = await function(*args, **kwargs)
                    _record_result(span, result)
                    return result
            return coroutine
        if inspect.isgeneratorfunction(function):
            @wraps(function)
            def generator(*args, **kwargs):
                with observation(name, as_type) as span:
                    stream = function(*args, **kwargs)
                    try:
                        for item in stream:
                            _record_result(span, item)
                            yield item
                    finally:
                        stream.close()
            return generator
        @wraps(function)
        def regular(*args, **kwargs):
            with observation(name, as_type) as span:
                result = function(*args, **kwargs)
                _record_result(span, result)
                return result
        return regular
    return decorate


def _record_result(span, result):
    if isinstance(result, dict):
        if result.get("success") is False or result.get("type") == "error" or result.get("status") == "failed":
            span.update(level="ERROR", status_message="Operation returned an error")
        elif result.get("status") == "partial":
            span.update(level="WARNING", status_message="Some documents could not be indexed")


@contextmanager
def trace_attributes(user_id=None, session_id=None):
    # ExitStack separates tracing setup failures from the request body.
    from contextlib import ExitStack
    with ExitStack() as stack:
        if get_langfuse() is not None:
            try:
                from langfuse import propagate_attributes
                stack.enter_context(propagate_attributes(
                    user_id=user_id, session_id=session_id, tags=["kiwi", "research"]
                ))
            except Exception:
                logger.warning("Langfuse attributes failed", exc_info=True)
        yield


def langchain_config():
    client = get_langfuse()
    if client is None:
        return {}
    try:
        from langfuse.langchain import CallbackHandler
        return {"callbacks": [CallbackHandler(public_key=get_settings().langfuse_public_key)]}
    except Exception:
        logger.warning("Langfuse callback initialization failed", exc_info=True)
        return {}


def enable_openai_tracing():
    """Langfuse's official drop-in instruments shared Gemini-compatible clients."""
    if get_langfuse() is not None:
        try:
            import langfuse.openai  # noqa: F401 - official SDK installs its wrappers on import
        except Exception:
            logger.warning("OpenAI-compatible tracing unavailable", exc_info=True)


def shutdown_langfuse():
    client = get_langfuse()
    if client is not None:
        try:
            client.shutdown()
        except Exception:
            logger.warning("Langfuse shutdown failed", exc_info=True)
