"""Finance / Groww MCP routes — same paths as grow-mcp for frontend parity."""

from __future__ import annotations

import json
import logging
from typing import Literal

from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import StreamingResponse
from pydantic import BaseModel, Field

from app.deps.rate_limit import rate_limit_dependency
from app.services.finance.chat_loop import chat_stream
from app.services.finance.mcp_client import get_mcp_tools

logger = logging.getLogger(__name__)
router = APIRouter(tags=["finance"])

_in_flight: set[str] = set()


class FinanceMessage(BaseModel):
    role: Literal["user", "model"]
    content: str = Field(min_length=1)


class FinanceChatBody(BaseModel):
    messages: list[FinanceMessage] = Field(min_length=1)


def _request_key(messages: list[FinanceMessage]) -> str:
    last = next((m for m in reversed(messages) if m.role == "user"), None)
    if not last:
        return ""
    return f"{len(messages)}:{last.content[:200]}"


@router.get("/health")
async def finance_health():
    from app.services.finance.mcp_client import get_mcp_client

    return {
        "status": "ok",
        "service": "ai-trading-assistant-backend",
        "mcp": get_mcp_client().connection_status(),
    }


@router.get("/api/tools")
async def list_tools():
    try:
        tools = await get_mcp_tools()
        return {
            "count": len(tools),
            "tools": [{"name": t["name"], "description": t.get("description")} for t in tools],
        }
    except Exception as e:
        raise HTTPException(500, detail={"error": "MCP not connected", "details": str(e)}) from e


@router.post("/api/chat")
async def finance_chat(
    body: FinanceChatBody,
    _: None = Depends(rate_limit_dependency),
):
    request_key = _request_key(body.messages)
    if request_key and request_key in _in_flight:
        raise HTTPException(429, detail="Request already in progress. Please wait.")
    if request_key:
        _in_flight.add(request_key)

    async def event_gen():
        try:
            payload = [m.model_dump() for m in body.messages]
            async for chunk in chat_stream(payload):
                yield f"data: {json.dumps(chunk)}\n\n"
            yield "data: [DONE]\n\n"
        except Exception as e:
            message = str(e)
            logger.error("[SSE Stream Error]: %s", message)
            yield f"data: {json.dumps({'error': message})}\n\n"
            yield "data: [DONE]\n\n"
        finally:
            if request_key:
                _in_flight.discard(request_key)

    return StreamingResponse(
        event_gen(),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "Connection": "keep-alive"},
    )
