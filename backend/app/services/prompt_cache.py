"""Gemini explicit prefix caching with a shared PostgreSQL TTL registry.

Only reusable instructions and research evidence enter caches. Evidence prefixes
are account-scoped; conversation history and generated answers are excluded.
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from functools import lru_cache
import hashlib
import json
import logging
from threading import Lock
import time

from google import genai
from google.genai import types
from prometheus_client import Counter

from app.config import get_settings
from app.services.observability import observation, request_user_id
from app.services.postgres import get_pool
from app.services.research.pdf_pipeline import token_count

logger = logging.getLogger(__name__)
_cache_usage = Counter('kiwi_prompt_cache_read_tokens_total', 'Provider-reported cached input tokens', ['model'])
_cache_events = Counter('kiwi_prompt_cache_events_total', 'Prompt cache generation outcomes', ['status'])
DDL = '''CREATE TABLE IF NOT EXISTS prompt_prefix_cache (
    key TEXT PRIMARY KEY, model TEXT NOT NULL, name TEXT,
    expires_at TIMESTAMPTZ, token_count INTEGER NOT NULL DEFAULT 0,
    uses INTEGER NOT NULL DEFAULT 0, retry_after TIMESTAMPTZ,
    updated_at TIMESTAMPTZ NOT NULL DEFAULT now()
)'''


def record_cache_usage(status, model, tokens):
    _cache_events.labels(status=status).inc()
    _cache_usage.labels(model=model).inc(max(0, tokens or 0))
    with observation('prompt_cache.usage', metadata={'cache_status':status,'cache_read_tokens':tokens or 0,'model':model}):
        pass


@dataclass
class CachedRequest:
    messages: list
    name: str | None = None
    key: str | None = None
    status: str = 'disabled'


@lru_cache(maxsize=1)
def get_prompt_cache():
    return PromptCache()


class PromptCache:
    def __init__(self, client=None):
        self.settings = get_settings()
        self.client = client
        self.initialized = False
        self.lock = Lock()
        self.unavailable_until = 0.0

    def _initialize(self):
        with self.lock:
            if not self.initialized:
                with get_pool().connection() as db:
                    db.execute(DDL)
                if self.client is None:
                    self.client = genai.Client(api_key=self.settings.google_api_key,
                                               http_options=types.HttpOptions(timeout=15000))
                self.initialized = True

    def prepare(self, messages, model, tools=None):
        original = CachedRequest(list(messages))
        if not self.settings.prompt_cache_enabled or time.monotonic() < self.unavailable_until:
            return original
        systems, prefix, offset = [], [], 0
        while offset < len(messages) and messages[offset].get('role') == 'system':
            systems.append(messages[offset].get('content', ''))
            offset += 1
        # This marker is generated internally by RAGAgent, before user history.
        if offset < len(messages) and messages[offset].get('role') == 'user' and messages[offset].get('content', '').startswith('<research_evidence>'):
            prefix.append(messages[offset]['content'])
            offset += 1
        system = '\n\n'.join(systems)
        estimate = token_count(system) + sum(token_count(text) for text in prefix)
        if not system or not (self.settings.prompt_cache_min_tokens <= estimate <= self.settings.prompt_cache_max_tokens):
            original.status = 'below_threshold' if estimate < self.settings.prompt_cache_min_tokens else 'too_large'
            return original
        scope = hashlib.sha256(str(request_user_id.get() or 'internal').encode()).hexdigest() if prefix else 'global-instructions'
        canonical = json.dumps({'model':model, 'system':system, 'evidence':prefix, 'tools':tools or [], 'scope':scope},
                               sort_keys=True, ensure_ascii=False, separators=(',', ':'))
        key = hashlib.sha256(canonical.encode()).hexdigest()
        try:
            self._initialize()
            with observation('prompt_cache.lookup', metadata={'cache_key':key}) as span:
                with get_pool().connection() as db, db.transaction():
                    db.execute('SELECT pg_advisory_xact_lock(hashtextextended(%s, 0))', ('kiwi:cache:' + key,))
                    row = db.execute('SELECT * FROM prompt_prefix_cache WHERE key=%s', (key,)).fetchone()
                    now = datetime.now(timezone.utc)
                    if row and row['name'] and row['expires_at'] and (row['expires_at'] - now).total_seconds() > 10:
                        db.execute('UPDATE prompt_prefix_cache SET uses=uses+1,updated_at=now() WHERE key=%s', (key,))
                        span.update(metadata={'cache_status':'hit','tokens':row['token_count'],'cache_key':key})
                        return CachedRequest(list(messages[offset:]), row['name'], key, 'hit')
                    if row and row['retry_after'] and row['retry_after'] > now:
                        return CachedRequest(list(messages), key=key, status='cooldown')
                    config = {'system_instruction':system, 'ttl':f'{self.settings.prompt_cache_ttl_seconds}s',
                              'display_name':'kiwi-' + key[:20]}
                    if prefix:
                        config['contents'] = [types.Content(role='user', parts=[types.Part(text=text)]) for text in prefix]
                    if tools:
                        declarations = [types.FunctionDeclaration(
                            name=tool['function']['name'], description=tool['function'].get('description', ''),
                            parameters_json_schema=tool['function'].get('parameters', {'type':'object'}),
                        ) for tool in tools]
                        config['tools'] = [types.Tool(function_declarations=declarations)]
                    try:
                        cached = self.client.caches.create(model=model, config=types.CreateCachedContentConfig(**config))
                    except Exception as error:
                        # Negative cache prevents retrying an unsupported prefix/model on every request.
                        db.execute('''INSERT INTO prompt_prefix_cache(key,model,retry_after) VALUES (%s,%s,now()+interval '60 seconds')
                            ON CONFLICT(key) DO UPDATE SET name=NULL,retry_after=EXCLUDED.retry_after,updated_at=now()''', (key,model))
                        span.update(metadata={'cache_status':'provider_unavailable','cache_key':key})
                        if 'limit=0' in str(error) or 'FreeTier' in str(error):
                            self.unavailable_until = time.monotonic() + 600
                        logger.warning('Explicit prompt cache unavailable (%s); using normal generation', type(error).__name__)
                        return CachedRequest(list(messages), key=key, status='provider_unavailable')
                    tokens = getattr(getattr(cached, 'usage_metadata', None), 'total_token_count', 0) or estimate
                    db.execute('''INSERT INTO prompt_prefix_cache(key,model,name,expires_at,token_count,uses)
                        VALUES (%s,%s,%s,%s,%s,1) ON CONFLICT(key) DO UPDATE SET name=EXCLUDED.name,
                        expires_at=EXCLUDED.expires_at,token_count=EXCLUDED.token_count,retry_after=NULL,
                        uses=prompt_prefix_cache.uses+1,updated_at=now()''', (key,model,cached.name,cached.expire_time,tokens))
                    span.update(metadata={'cache_status':'created','cache_key':key,'tokens':tokens})
                    return CachedRequest(list(messages[offset:]), cached.name, key, 'created')
        except Exception:
            # DB/cache outages cannot block text generation. Circuit-break for 30 seconds.
            self.unavailable_until = time.monotonic() + 30
            logger.warning('Prompt cache registry unavailable; generating uncached', exc_info=True)
            return CachedRequest(list(messages), key=key, status='unavailable')

    def invalidate(self, request):
        if request.key:
            try:
                with get_pool().connection() as db:
                    db.execute('UPDATE prompt_prefix_cache SET name=NULL,expires_at=now(),retry_after=now()+interval \'30 seconds\' WHERE key=%s AND name=%s',
                               (request.key, request.name))
            except Exception:
                logger.warning('Failed to invalidate stale prompt cache', exc_info=True)

    @staticmethod
    def rejected(error):
        code = getattr(error, 'status_code', getattr(error, 'code', None))
        return code in {400,404} and any(word in str(error).lower() for word in ['cache', 'cachedcontent', 'not found'])
