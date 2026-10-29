"""Research tests must never export traces using developer credentials."""
import pytest
import os
from app.config import get_settings
from app.services.observability import get_langfuse


@pytest.fixture(autouse=True)
def disable_external_tracing(monkeypatch):
    monkeypatch.setenv("LANGFUSE_ENABLED", "false")
    monkeypatch.setenv("PROMPT_CACHE_ENABLED", "false")
    if os.getenv("TEST_DATABASE_URL"):
        monkeypatch.setenv("DATABASE_URL", os.environ["TEST_DATABASE_URL"])
    else:
        # A test must never silently use the developer's production database.
        monkeypatch.setenv("DATABASE_URL", "postgresql://invalid:invalid@127.0.0.1:1/no_test_database")
    get_settings.cache_clear()
    get_langfuse.cache_clear()
    yield
    get_settings.cache_clear()
    get_langfuse.cache_clear()
