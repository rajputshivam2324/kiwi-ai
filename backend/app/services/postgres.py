"""Bounded PostgreSQL pool for synchronous RAG workers and memory operations.

Independent of event-loop lifetime; safe with Neon transaction pooling. All
advisory locks are transaction-scoped, never session-scoped.
"""
from functools import lru_cache
from psycopg.rows import dict_row
from psycopg_pool import ConnectionPool
from app.config import get_settings


@lru_cache(maxsize=4)
def _pool(dsn: str, size: int):
    pool = ConnectionPool(
        conninfo=dsn, min_size=0, max_size=size, timeout=20, max_idle=120, open=True,
        kwargs={"autocommit": True, "row_factory": dict_row, "connect_timeout": 10,
                "prepare_threshold": None},
    )
    _created_pools.append(pool)
    return pool


def close_postgres():
    # Pool ownership is process-wide; no connections are tied to asyncio loops.
    for pool in _created_pools:
        pool.close()
    _created_pools.clear()
    _pool.cache_clear()


_created_pools = []


def get_pool():
    settings = get_settings()
    return _pool(settings.database_url, settings.postgres_pool_size)
