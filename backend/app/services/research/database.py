import asyncpg
import uuid
import json
import logging
from datetime import datetime
from typing import List, Dict, Any, Optional
from app.config import get_settings

logger = logging.getLogger(__name__)

# Connection pool singleton
_pool: Optional[asyncpg.Pool] = None


async def get_pool() -> asyncpg.Pool:
    """Get or create the connection pool"""
    global _pool
    if _pool is None:
        settings = get_settings()
        _pool = await asyncpg.create_pool(
            dsn=settings.database_url,
            min_size=2,
            max_size=10,
            command_timeout=60
        )
        logger.info("PostgreSQL connection pool created")
    return _pool


async def close_pool():
    """Close the connection pool"""
    global _pool
    if _pool:
        await _pool.close()
        _pool = None
        logger.info("PostgreSQL connection pool closed")


async def init_db():
    """Create tables if they don't exist"""
    pool = await get_pool()
    async with pool.acquire() as conn:
        await conn.execute("""
            CREATE TABLE IF NOT EXISTS arxiv_conversations (
                id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
                user_id TEXT NOT NULL,
                title TEXT NOT NULL DEFAULT 'New Research Chat',
                created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
                updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
            );
            
            CREATE INDEX IF NOT EXISTS idx_arxiv_conv_user 
                ON arxiv_conversations(user_id, updated_at DESC);
        """)
        
        await conn.execute("""
            CREATE TABLE IF NOT EXISTS arxiv_messages (
                id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
                conversation_id UUID NOT NULL REFERENCES arxiv_conversations(id) ON DELETE CASCADE,
                role TEXT NOT NULL CHECK (role IN ('user', 'assistant', 'system')),
                content TEXT NOT NULL,
                sources JSONB DEFAULT '[]'::jsonb,
                created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
            );
            
            CREATE INDEX IF NOT EXISTS idx_arxiv_msg_conv 
                ON arxiv_messages(conversation_id, created_at ASC);
        """)
        
        logger.info("Database tables initialized successfully")


# ─── Conversation CRUD ───────────────────────────────────────────────

async def create_conversation(user_id: str, title: str = "New Research Chat") -> str:
    """Create a new conversation, returns conversation ID"""
    pool = await get_pool()
    conv_id = str(uuid.uuid4())
    async with pool.acquire() as conn:
        await conn.execute(
            """
            INSERT INTO arxiv_conversations (id, user_id, title)
            VALUES ($1, $2, $3)
            """,
            uuid.UUID(conv_id), user_id, title
        )
    logger.info(f"Created conversation {conv_id} for user {user_id}")
    return conv_id


async def list_conversations(user_id: str, limit: int = 50) -> List[Dict[str, Any]]:
    """List conversations for a user, most recent first"""
    pool = await get_pool()
    async with pool.acquire() as conn:
        rows = await conn.fetch(
            """
            SELECT 
                c.id, c.title, c.created_at, c.updated_at,
                (SELECT COUNT(*) FROM arxiv_messages m WHERE m.conversation_id = c.id) as message_count
            FROM arxiv_conversations c
            WHERE c.user_id = $1
            ORDER BY c.updated_at DESC
            LIMIT $2
            """,
            user_id, limit
        )
    
    return [
        {
            "id": str(row["id"]),
            "title": row["title"],
            "created_at": row["created_at"].isoformat(),
            "updated_at": row["updated_at"].isoformat(),
            "message_count": row["message_count"]
        }
        for row in rows
    ]


async def get_conversation_messages(conversation_id: str) -> List[Dict[str, Any]]:
    """Get all messages for a conversation"""
    pool = await get_pool()
    async with pool.acquire() as conn:
        rows = await conn.fetch(
            """
            SELECT id, role, content, sources, created_at
            FROM arxiv_messages
            WHERE conversation_id = $1
            ORDER BY created_at ASC
            """,
            uuid.UUID(conversation_id)
        )
    
    return [
        {
            "id": str(row["id"]),
            "role": row["role"],
            "content": row["content"],
            "sources": json.loads(row["sources"]) if row["sources"] else [],
            "created_at": row["created_at"].isoformat()
        }
        for row in rows
    ]


async def add_message(
    conversation_id: str,
    role: str,
    content: str,
    sources: List[Dict[str, Any]] = None
) -> str:
    """Add a message to a conversation, returns message ID"""
    pool = await get_pool()
    msg_id = str(uuid.uuid4())
    sources_json = json.dumps(sources or [])
    
    async with pool.acquire() as conn:
        # Insert message
        await conn.execute(
            """
            INSERT INTO arxiv_messages (id, conversation_id, role, content, sources)
            VALUES ($1, $2, $3, $4, $5::jsonb)
            """,
            uuid.UUID(msg_id),
            uuid.UUID(conversation_id),
            role,
            content,
            sources_json
        )
        
        # Update conversation's updated_at timestamp
        await conn.execute(
            """
            UPDATE arxiv_conversations SET updated_at = NOW()
            WHERE id = $1
            """,
            uuid.UUID(conversation_id)
        )
    
    return msg_id


async def update_conversation_title(conversation_id: str, title: str):
    """Update conversation title"""
    pool = await get_pool()
    async with pool.acquire() as conn:
        await conn.execute(
            """
            UPDATE arxiv_conversations SET title = $1, updated_at = NOW()
            WHERE id = $2
            """,
            title,
            uuid.UUID(conversation_id)
        )


async def delete_conversation(conversation_id: str):
    """Delete a conversation and all its messages (CASCADE)"""
    pool = await get_pool()
    async with pool.acquire() as conn:
        await conn.execute(
            "DELETE FROM arxiv_conversations WHERE id = $1",
            uuid.UUID(conversation_id)
        )
    logger.info(f"Deleted conversation {conversation_id}")


async def auto_title_conversation(conversation_id: str, first_message: str):
    """Auto-generate a title from the first user message"""
    # Truncate to first 60 chars, clean up
    title = first_message.strip()
    if len(title) > 60:
        title = title[:57] + "..."
    # Remove newlines
    title = title.replace("\n", " ").replace("\r", "")
    
    await update_conversation_title(conversation_id, title)
