"""Async route adapters over the shared PostgreSQL conversation memory store."""
import asyncio
from functools import lru_cache
from app.services.memory import ConversationMemory


@lru_cache(maxsize=1)
def get_memory():
    return ConversationMemory()


async def init_db():
    await asyncio.to_thread(get_memory)


async def close_pool():
    get_memory.cache_clear()  # Shared pool is closed by application lifespan.


async def create_conversation(user_id, title='New Research Chat'):
    return await asyncio.to_thread(get_memory().create, user_id, title)


async def list_conversations(user_id, limit=50):
    return await asyncio.to_thread(get_memory().list, user_id, limit)


async def get_conversation_messages(conversation_id, user_id):
    return await asyncio.to_thread(get_memory().messages, conversation_id, user_id)


async def delete_conversation(conversation_id, user_id):
    return await asyncio.to_thread(get_memory().delete, conversation_id, user_id)


async def add_message(conversation_id, role, content, sources=None, *, user_id):
    return await asyncio.to_thread(get_memory().append, conversation_id, user_id, role, content, sources)


async def auto_title_conversation(conversation_id, first_message, *, user_id):
    await asyncio.to_thread(get_memory().title, conversation_id, user_id, first_message)
