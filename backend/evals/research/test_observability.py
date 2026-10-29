"""Tracing isolation, streaming lifecycle, content privacy, and LLM callbacks."""
import asyncio
from contextlib import contextmanager
from types import SimpleNamespace
from unittest.mock import Mock

import pytest

from app.services import observability as telemetry
from app.services.research.llm_service import LLMService


@pytest.fixture
def recorded_client(monkeypatch):
    events = []
    class Client:
        @contextmanager
        def start_as_current_observation(self, **kwargs):
            events.append(("start", kwargs["name"]))
            try:
                yield Mock()
            finally:
                events.append(("end", kwargs["name"]))
    monkeypatch.setattr(telemetry, "get_langfuse", lambda: Client())
    return events


def test_sync_stream_span_lives_until_consumed_or_closed(recorded_client):
    @telemetry.traced("stream")
    def stream():
        yield "one"
        yield "two"
    iterator = stream()
    assert recorded_client == []
    assert next(iterator) == "one"
    assert recorded_client == [("start", "stream")]
    iterator.close()
    assert recorded_client == [("start", "stream"), ("end", "stream")]


def test_async_stream_span_closes_on_cancellation(recorded_client):
    @telemetry.traced("async-stream")
    async def stream():
        yield "one"
        yield "two"
    async def consume():
        iterator = stream()
        assert await anext(iterator) == "one"
        assert recorded_client == [("start", "async-stream")]
        await iterator.aclose()
    asyncio.run(consume())
    assert recorded_client[-1] == ("end", "async-stream")


def test_sdk_failure_does_not_repeat_or_hide_application_error(monkeypatch):
    client = Mock()
    client.start_as_current_observation.side_effect = RuntimeError("collector unavailable")
    monkeypatch.setattr(telemetry, "get_langfuse", lambda: client)
    runs = []
    @telemetry.traced("application")
    def application():
        runs.append(1)
        raise ValueError("real application failure")
    with pytest.raises(ValueError, match="real application"):
        application()
    assert runs == [1]


def test_span_shutdown_failure_does_not_fail_request(monkeypatch):
    class Manager:
        def __enter__(self):
            return Mock()
        def __exit__(self, *args):
            raise RuntimeError("telemetry failed")
    monkeypatch.setattr(telemetry, "get_langfuse", lambda: SimpleNamespace(start_as_current_observation=lambda **_: Manager()))
    with telemetry.observation("check"):
        pass
    with pytest.raises(ValueError, match="application"):
        with telemetry.observation("check"):
            raise ValueError("application")


def test_disabled_tracing_does_not_construct_sdk(monkeypatch):
    monkeypatch.setattr(telemetry, "get_settings", lambda: SimpleNamespace(langfuse_enabled=False))
    telemetry.get_langfuse.cache_clear()
    try:
        assert telemetry.get_langfuse() is None
        assert telemetry.langchain_config() == {}
    finally:
        telemetry.get_langfuse.cache_clear()


def test_content_mask_preserves_operational_metrics():
    assert telemetry._mask_content(data="private prompt") == "[content capture disabled]"
    masked = telemetry._mask_content(data={"documents": 32, "pages": 80, "prompt": "private"})
    assert masked["documents"] == 32 and masked["pages"] == 80
    assert "private" not in str(masked)


def test_langchain_callbacks_passed_to_invoke_and_stream(monkeypatch):
    monkeypatch.setattr("app.services.research.llm_service.langchain_config", lambda: {"callbacks": ["handler"]})
    service = LLMService.__new__(LLMService)
    from app.config import get_settings
    service.settings = get_settings()
    service.client = Mock()
    service.client.invoke.return_value = SimpleNamespace(content="answer", additional_kwargs={})
    service.client.stream.return_value = iter([SimpleNamespace(content="chunk", additional_kwargs={})])
    assert service.invoke([{"role": "user", "content": "question"}])["content"] == "answer"
    assert list(service.stream([])) == [{"type": "content", "data": "chunk"}]
    assert service.client.invoke.call_args.kwargs["config"]["callbacks"] == ["handler"]
    assert service.client.stream.call_args.kwargs["config"]["callbacks"] == ["handler"]


def test_langchain_content_blocks_are_normalized_without_thoughts():
    from app.services.research.llm_service import _text_content
    assert _text_content([
        {"type": "text", "text": "Public answer"},
        {"type": "text", "text": "Private thought", "thought": True},
        {"type": "image", "source": "ignored"},
    ]) == "Public answer"


def test_actual_sdk_exports_nested_spans_without_content(monkeypatch):
    from langfuse import Langfuse
    from opentelemetry.sdk.trace import TracerProvider
    from opentelemetry.sdk.trace.export.in_memory_span_exporter import InMemorySpanExporter
    exporter = InMemorySpanExporter()
    client = Langfuse(public_key="pk-lf-offline-test", secret_key="sk-lf-offline-test",
                      tracer_provider=TracerProvider(), span_exporter=exporter,
                      mask=telemetry._mask_content)
    monkeypatch.setattr(telemetry, "get_langfuse", lambda: client)
    try:
        with telemetry.observation("parent"):
            with telemetry.observation("child", input="private-prompt", metadata={"pages": 80}):
                pass
        client.flush()
        spans = {span.name: span for span in exporter.get_finished_spans()}
        assert spans["child"].parent.span_id == spans["parent"].context.span_id
        attributes = str(spans["child"].attributes)
        assert "private-prompt" not in attributes
        assert "80" in attributes
    finally:
        client.shutdown()


def test_rejected_cached_generation_retries_original_prompt_once(monkeypatch):
    from app.config import get_settings
    from app.services.prompt_cache import CachedRequest
    service=LLMService.__new__(LLMService)
    service.settings=get_settings()
    service.client=Mock()
    error=RuntimeError('cached content no longer exists')
    service.client.invoke.side_effect=[error,SimpleNamespace(content='answer',additional_kwargs={},usage_metadata={})]
    cache=Mock()
    cache.prepare.return_value=CachedRequest([{'role':'user','content':'question'}],'cachedContents/expired','key','hit')
    cache.rejected.return_value=True
    monkeypatch.setattr('app.services.research.llm_service.get_prompt_cache',lambda:cache)
    messages=[{'role':'system','content':'Original system instructions'},{'role':'user','content':'question'}]
    assert service.invoke(messages)['content'] == 'answer'
    assert service.client.invoke.call_count == 2
    assert service.client.invoke.call_args.args[0] == messages
    cache.invalidate.assert_called_once()
