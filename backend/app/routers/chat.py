"""General Kiwi AI chat (non-builder) — SSE streaming."""

from __future__ import annotations

import json
import logging

from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import StreamingResponse

from app.deps.auth import require_auth
from app.deps.rate_limit import rate_limit_dependency
from app.services.builder.prompts import CHAT_SYSTEM
from app.services.gemini_client import stream_chat_with_retry
from app.config import get_settings

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/api/chat", tags=["chat"])


@router.post("/message")
async def chat_message(
    request: Request,
    user_id: str = Depends(require_auth),
    _: None = Depends(rate_limit_dependency),
):
    body = await request.json()
    message = body.get("message")
    history = body.get("history") or []
    if not message:
        raise HTTPException(400, detail="No message provided")

    settings = get_settings()
    if not settings.gemini_api_key:
        raise HTTPException(500, detail="GEMINI_API_KEY or GOOGLE_API_KEY not configured")

    conversation_history = [
        {
            "role": "user" if msg.get("role") == "user" else "assistant",
            "content": msg.get("content", ""),
        }
        for msg in history
    ]
    messages = [
        {"role": "system", "content": CHAT_SYSTEM},
        *conversation_history,
        {"role": "user", "content": message},
    ]

    async def event_gen():
        try:
            async for chunk in stream_chat_with_retry(
                messages=messages,
                model=settings.llm_model,
                temperature=0.6,
                top_p=0.9,
                max_tokens=4096,
            ):
                delta = chunk.choices[0].delta if chunk.choices else None
                if delta and getattr(delta, "content", None):
                    yield f"data: {json.dumps({'content': delta.content})}\n\n"
            yield "data: [DONE]\n\n"
        except Exception as e:
            logger.error("Chat error: %s", e)
            yield f"data: {json.dumps({'error': 'Stream error'})}\n\n"

    return StreamingResponse(
        event_gen(),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "Connection": "keep-alive"},
    )
