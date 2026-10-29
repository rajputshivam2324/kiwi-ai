"""Real registry, deterministic provider double: TTL, invalidation, and privacy."""
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timedelta, timezone
from types import SimpleNamespace
from unittest.mock import Mock
import os
import uuid
import pytest

from app.config import get_settings
from app.services.prompt_cache import PromptCache
from app.services.observability import trace_attributes
from app.services.postgres import get_pool


@pytest.fixture
def cache(monkeypatch):
    if not os.getenv('TEST_DATABASE_URL'):
        pytest.skip('TEST_DATABASE_URL required')
    monkeypatch.setenv('PROMPT_CACHE_ENABLED','true')
    monkeypatch.setenv('PROMPT_CACHE_MIN_TOKENS','16')
    get_settings.cache_clear()
    provider=Mock()
    provider.caches.create.side_effect=lambda **_:SimpleNamespace(
        name='cachedContents/' + uuid.uuid4().hex, expire_time=datetime.now(timezone.utc)+timedelta(minutes=10),
        usage_metadata=SimpleNamespace(total_token_count=100))
    service=PromptCache(provider)
    model='test-' + uuid.uuid4().hex
    yield service,provider,model
    if service.initialized:
        with get_pool().connection() as db:
            db.execute('DELETE FROM prompt_prefix_cache WHERE model=%s',(model,))


def messages():
    return [{'role':'system','content':'Follow the research evidence carefully. ' * 12},
            {'role':'user','content':'private question'}, {'role':'assistant','content':'private answer'},
            {'role':'user','content':'follow up'}]


def test_prefix_cached_once_reused_without_caching_history(cache):
    service,provider,model=cache
    original=messages()
    first=service.prepare(original,model)
    second=service.prepare(original,model)
    assert first.status == 'created' and second.status == 'hit'
    assert first.name == second.name
    assert second.messages == original[1:]
    provider.caches.create.assert_called_once()
    assert 'private question' not in str(provider.caches.create.call_args)
    assert 'private answer' not in str(provider.caches.create.call_args)


def test_expired_cache_is_recreated(cache):
    service,provider,model=cache
    first=service.prepare(messages(),model)
    with get_pool().connection() as db:
        db.execute("UPDATE prompt_prefix_cache SET expires_at=now()-interval '1 minute' WHERE key=%s",(first.key,))
    second=service.prepare(messages(),model)
    assert second.status == 'created' and second.name != first.name
    assert provider.caches.create.call_count == 2


def test_model_and_instruction_changes_invalidate_prefix(cache):
    service,provider,model=cache
    first=service.prepare(messages(),model)
    changed=messages(); changed[0]['content'] += 'Use different instructions.'
    second=service.prepare(changed,model)
    assert first.key != second.key and first.name != second.name


def test_provider_failure_falls_back_and_uses_negative_cache(cache):
    service,provider,model=cache
    provider.caches.create.side_effect=RuntimeError('cache quota unavailable')
    first=service.prepare(messages(),model)
    second=service.prepare(messages(),model)
    assert first.name is None and first.messages == messages()
    assert first.status == 'provider_unavailable' and second.status == 'cooldown'
    assert provider.caches.create.call_count == 1


def test_invalidation_does_not_remove_a_replaced_cache(cache):
    service,provider,model=cache
    first=service.prepare(messages(),model)
    service.invalidate(first)
    assert service.prepare(messages(),model).name is None
    assert service.prepare(messages(),model).messages == messages()


def test_concurrent_requests_do_not_create_duplicate_provider_caches(cache):
    service,provider,model=cache
    with ThreadPoolExecutor(max_workers=4) as executor:
        requests=list(executor.map(lambda _:service.prepare(messages(),model),range(8)))
    assert len({r.name for r in requests}) == 1
    assert provider.caches.create.call_count == 1


def test_evidence_cache_is_user_scoped(cache):
    service,provider,model=cache
    original=messages()
    original.insert(1,{'role':'user','content':'<research_evidence>Public paper evidence</research_evidence>'})
    with trace_attributes('user-one'):
        one=service.prepare(original,model)
    with trace_attributes('user-two'):
        two=service.prepare(original,model)
    assert one.key != two.key and one.name != two.name
    assert one.messages == original[2:]


def test_small_prefix_skips_provider_and_registry(cache):
    service,provider,model=cache
    result=service.prepare([{'role':'system','content':'Be helpful'},{'role':'user','content':'hi'}],model)
    assert result.status == 'below_threshold' and result.name is None
    assert not service.initialized and not provider.caches.create.called
