"""Research tests must never export traces using developer credentials."""
import pytest
from app.config import get_settings
from app.services.observability import get_langfuse


@pytest.fixture(autouse=True)
def disable_external_tracing(monkeypatch):
    monkeypatch.setenv("LANGFUSE_ENABLED", "false")
    get_settings.cache_clear()
    get_langfuse.cache_clear()
    yield
    get_settings.cache_clear()
    get_langfuse.cache_clear()
