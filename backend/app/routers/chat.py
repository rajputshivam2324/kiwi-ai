"""General chat with owned durable memory and bounded model context."""
from __future__ import annotations

import asyncio
import json
import logging
from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import StreamingResponse

from app.deps.auth import require_auth
from app.deps.rate_limit import rate_limit_dependency
from app.services.builder.prompts import CHAT_SYSTEM
from app.services.gemini_client import stream_chat_with_retry
from app.services.memory import ConversationMemory, MemoryNotFound, MemoryBusy, bounded_history
from app.services.observability import trace_attributes
from app.services.research.database import get_memory

logger = logging.getLogger(__name__)
router = APIRouter(prefix='/api/chat', tags=['chat'])


@router.post('/message')
async def chat_message(request: Request, user_id: str = Depends(require_auth),
                       memory: ConversationMemory = Depends(get_memory),
                       _: None = Depends(rate_limit_dependency)):
    body = await request.json()
    message = body.get('message')
    if not isinstance(message, str) or not message.strip() or len(message) > 32000:
        raise HTTPException(422, detail='A message of 1–32000 characters is required')
    try:
        conversation_id, turn_id = await asyncio.to_thread(memory.begin_turn, user_id, message, body.get('conversation_id'), 'chat')
        history = await asyncio.to_thread(memory.context, conversation_id, user_id, turn_id)
    except MemoryNotFound as error:
        raise HTTPException(404, detail='Conversation not found') from error
    except MemoryBusy as error:
        raise HTTPException(409, detail=str(error)) from error
    except BaseException:
        if 'turn_id' in locals():
            await asyncio.to_thread(memory.finish_turn, conversation_id, user_id, turn_id)
        raise
    if not body.get('conversation_id') and not history:
        history = bounded_history(body.get('history') or [])
    messages = [{'role':'system','content':CHAT_SYSTEM}, *history, {'role':'user','content':message}]

    async def event_gen():
        answer, successful = '', False
        try:
            yield f"data: {json.dumps({'conversation_id':conversation_id})}\n\n"
            with trace_attributes(user_id, conversation_id):
                async for chunk in stream_chat_with_retry(messages=messages, temperature=.6, top_p=.9, max_tokens=4096):
                    delta = chunk.choices[0].delta if chunk.choices else None
                    if delta and getattr(delta, 'content', None):
                        answer += delta.content
                        yield f"data: {json.dumps({'content':delta.content})}\n\n"
            successful = True
            yield 'data: [DONE]\n\n'
        except Exception:
            logger.exception('Chat generation failed')
            yield f"data: {json.dumps({'error':'Stream error'})}\n\n"
        finally:
            await asyncio.shield(asyncio.to_thread(memory.finish_turn, conversation_id, user_id, turn_id,
                                                   answer if successful else None))
    return StreamingResponse(event_gen(), media_type='text/event-stream',
                             headers={'Cache-Control':'no-cache','Connection':'keep-alive'})
