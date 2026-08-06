"""Research / arXiv RAG routes — same paths as backend-3 for frontend parity."""

from __future__ import annotations

import asyncio
import json
import logging
from typing import AsyncIterator

from fastapi import APIRouter, Depends, HTTPException, Query
from fastapi.responses import StreamingResponse

from app.config import get_settings
from app.deps.rate_limit import rate_limit_dependency
from app.models.research import (
    ChatRequest,
    ChatResponse,
    ConversationCreate,
    ConversationListResponse,
    ConversationMessagesResponse,
    ConversationSummary,
    IngestRequest,
    IngestResponse,
    MessageOut,
)
from app.services.research.database import (
    add_message,
    auto_title_conversation,
    create_conversation,
    delete_conversation,
    get_conversation_messages,
    list_conversations,
)
from app.services.research.rag_agent import RAGAgent, get_rag_agent
from app.services.research.vectorstore import VectorStoreService, get_vectorstore_service

logger = logging.getLogger(__name__)
router = APIRouter(tags=["research"])
settings = get_settings()


@router.get("/")
async def research_root():
    return {
        "status": "healthy",
        "service": "arXiv RAG Chatbot",
        "version": "2.0.0",
        "unified": True,
    }


@router.get("/stats")
async def get_stats(
    vectorstore: VectorStoreService = Depends(get_vectorstore_service),
):
    try:
        count = vectorstore.get_collection_count()
        return {
            "total_documents": count,
            "collection_name": settings.collection_name,
            "embedding_model": settings.embedding_model,
        }
    except Exception as e:
        raise HTTPException(500, detail=str(e)) from e


@router.post("/conversations")
async def create_new_conversation(request: ConversationCreate):
    try:
        conv_id = await create_conversation(
            user_id=request.user_id, title=request.title
        )
        return {"conversation_id": conv_id, "title": request.title}
    except Exception as e:
        raise HTTPException(500, detail=str(e)) from e


@router.get("/conversations", response_model=ConversationListResponse)
async def get_conversations(user_id: str = Query(..., description="User ID")):
    try:
        convs = await list_conversations(user_id)
        return ConversationListResponse(
            conversations=[ConversationSummary(**c) for c in convs]
        )
    except Exception as e:
        raise HTTPException(500, detail=str(e)) from e


@router.get(
    "/conversations/{conversation_id}/messages",
    response_model=ConversationMessagesResponse,
)
async def get_messages(conversation_id: str):
    try:
        msgs = await get_conversation_messages(conversation_id)
        return ConversationMessagesResponse(
            conversation_id=conversation_id,
            messages=[MessageOut(**m) for m in msgs],
        )
    except Exception as e:
        raise HTTPException(500, detail=str(e)) from e


@router.delete("/conversations/{conversation_id}")
async def remove_conversation(conversation_id: str):
    try:
        await delete_conversation(conversation_id)
        return {"status": "deleted", "conversation_id": conversation_id}
    except Exception as e:
        raise HTTPException(500, detail=str(e)) from e


@router.post("/chat", response_model=ChatResponse)
async def chat(
    request: ChatRequest,
    rag_agent: RAGAgent = Depends(get_rag_agent),
    _: None = Depends(rate_limit_dependency),
):
    try:
        history = []
        if request.conversation_id:
            db_messages = await get_conversation_messages(request.conversation_id)
            history = [
                {"role": m["role"], "content": m["content"]} for m in db_messages
            ]
        else:
            history = [
                {"role": msg.role, "content": msg.content}
                for msg in request.conversation_history
            ]

        result = rag_agent.query(
            user_query=request.message, conversation_history=history, k=3
        )

        conv_id = request.conversation_id
        if request.user_id:
            if not conv_id:
                conv_id = await create_conversation(request.user_id)
                await auto_title_conversation(conv_id, request.message)
            await add_message(conv_id, "user", request.message)
            await add_message(
                conv_id, "assistant", result["answer"], result.get("sources")
            )

        return ChatResponse(
            answer=result["answer"],
            sources=result["sources"],
            reasoning=result.get("reasoning"),
            conversation_id=conv_id,
        )
    except Exception as e:
        logger.error("Error in chat endpoint: %s", e)
        raise HTTPException(500, detail=str(e)) from e


async def generate_chat_stream(
    message: str,
    conversation_history: list,
    rag_agent: RAGAgent,
    conversation_id: str | None = None,
    user_id: str | None = None,
) -> AsyncIterator[str]:
    try:
        conv_id = conversation_id
        is_new = False
        if user_id and not conv_id:
            conv_id = await create_conversation(user_id)
            is_new = True

        if conv_id:
            yield f"data: {json.dumps({'type': 'conversation_id', 'data': conv_id})}\n\n"

        if conv_id:
            await add_message(conv_id, "user", message)
            if is_new:
                await auto_title_conversation(conv_id, message)

        full_response = ""
        sources_data: list = []
        queue: asyncio.Queue = asyncio.Queue()
        sentinel = object()

        def _run_sync_stream():
            try:
                for chunk in rag_agent.query_stream(
                    user_query=message,
                    conversation_history=conversation_history,
                    k=3,
                ):
                    queue.put_nowait(chunk)
            except Exception as stream_err:
                queue.put_nowait({"type": "error", "data": str(stream_err)})
            finally:
                queue.put_nowait(sentinel)

        loop = asyncio.get_event_loop()
        stream_task = loop.run_in_executor(None, _run_sync_stream)

        while True:
            chunk = await queue.get()
            if chunk is sentinel:
                break
            if chunk.get("type") == "content":
                full_response += chunk.get("data", "")
            elif chunk.get("type") == "sources":
                sources_data = chunk.get("data", [])
            yield f"data: {json.dumps(chunk)}\n\n"

        await stream_task

        if conv_id and full_response:
            db_sources = []
            for s in sources_data[:10]:
                meta = s.get("metadata", {})
                db_sources.append(
                    {
                        "title": meta.get("title", ""),
                        "arxiv_id": meta.get("arxiv_id", ""),
                        "url": meta.get("url", meta.get("pdf_url", "")),
                    }
                )
            await add_message(conv_id, "assistant", full_response, db_sources)

        yield "data: [DONE]\n\n"
    except Exception as e:
        logger.error("Error in streaming: %s", e)
        yield f"data: {json.dumps({'type': 'error', 'data': str(e)})}\n\n"


@router.post("/chat/stream")
async def chat_stream(
    request: ChatRequest,
    rag_agent: RAGAgent = Depends(get_rag_agent),
    _: None = Depends(rate_limit_dependency),
):
    try:
        if request.conversation_id:
            db_messages = await get_conversation_messages(request.conversation_id)
            history = [
                {"role": m["role"], "content": m["content"]} for m in db_messages
            ]
        else:
            history = [
                {"role": msg.role, "content": msg.content}
                for msg in request.conversation_history
            ]

        return StreamingResponse(
            generate_chat_stream(
                message=request.message,
                conversation_history=history,
                rag_agent=rag_agent,
                conversation_id=request.conversation_id,
                user_id=request.user_id,
            ),
            media_type="text/event-stream",
            headers={"Cache-Control": "no-cache", "Connection": "keep-alive"},
        )
    except Exception as e:
        raise HTTPException(500, detail=str(e)) from e


@router.post("/ingest", response_model=IngestResponse)
async def ingest_arxiv(
    request: IngestRequest,
    vectorstore: VectorStoreService = Depends(get_vectorstore_service),
):
    try:
        from app.scripts.ingest_arxiv import ingest_papers

        result = ingest_papers(
            query=request.query,
            max_results=request.max_results,
            vectorstore=vectorstore,
        )
        return IngestResponse(
            status="success",
            documents_added=result["documents_added"],
            arxiv_ids=result["arxiv_ids"],
        )
    except Exception as e:
        raise HTTPException(500, detail=str(e)) from e


@router.delete("/reset")
async def reset_database(
    vectorstore: VectorStoreService = Depends(get_vectorstore_service),
):
    try:
        vectorstore.reset_collection()
        return {"status": "success", "message": "Vector database has been reset"}
    except Exception as e:
        raise HTTPException(500, detail=str(e)) from e
