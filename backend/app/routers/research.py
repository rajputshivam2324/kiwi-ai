"""Research / arXiv RAG routes — same paths as backend-3 for frontend parity."""

from __future__ import annotations

import asyncio
import json
import logging
from contextvars import copy_context
from threading import Event
from typing import AsyncIterator

from fastapi import APIRouter, Depends, HTTPException, Query
from fastapi.responses import StreamingResponse

from app.config import get_settings
from app.deps.rate_limit import rate_limit_dependency
from app.deps.auth import require_auth
from app.services.memory import ConversationMemory, MemoryNotFound, MemoryBusy
from app.services.research.database import get_memory

from app.services.observability import trace_attributes, traced

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


@router.get("/api/research/health")
async def research_health():
    """Research diagnostics — arXiv connectivity + knowledge base size."""
    from app.services.research.arxiv_client import connectivity_check

    diag = connectivity_check()
    kb_count = 0
    kb_error = None
    try:
        vs = get_vectorstore_service()
        kb_count = vs.get_collection_count()
    except Exception as e:
        kb_error = str(e)

    ok = diag.get("search_ok", False)
    return {
        "status": "ok" if ok else "degraded",
        "arxiv_reachable": ok,
        "arxiv_sample": diag.get("sample_title"),
        "arxiv_errors": diag.get("errors") or None,
        "connectivity": diag,
        "knowledge_base_documents": kb_count,
        "knowledge_base_error": kb_error,
    }

@router.get("/api/research/search")
@traced("research.search_papers", "tool")
async def research_search_test(q: str = Query(..., min_length=2)):
    """Debug endpoint — test live arXiv search and return raw results."""
    from app.services.research.arxiv_client import search_papers

    try:
        papers = search_papers(q, max_results=5)
        return {"success": True, "count": len(papers), "papers": papers}
    except Exception as e:
        from app.services.research.arxiv_client import connectivity_check

        return {
            "success": False,
            "error": str(e),
            "connectivity": connectivity_check(),
        }


@router.get("/health")
async def research_health_legacy():
    """Legacy path — prefer GET /api/research/health (finance also mounts /health)."""
    return await research_health()


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


def _memory_error(error):
    if isinstance(error, MemoryNotFound):
        return HTTPException(404, detail="Conversation not found")
    if isinstance(error, MemoryBusy):
        return HTTPException(409, detail=str(error))
    return HTTPException(500, detail="Research request failed")


@router.post("/conversations")
async def create_new_conversation(request: ConversationCreate, user_id: str = Depends(require_auth),
                                  memory: ConversationMemory = Depends(get_memory)):
    if request.user_id != user_id:
        raise HTTPException(403, detail="User ID does not match authenticated user")
    conv_id = await asyncio.to_thread(memory.create, user_id, request.title)
    return {"conversation_id":conv_id, "title":request.title}


@router.get("/conversations", response_model=ConversationListResponse)
async def get_conversations(user_id: str | None = Query(None), actor: str = Depends(require_auth),
                            memory: ConversationMemory = Depends(get_memory)):
    if user_id and user_id != actor:
        raise HTTPException(403, detail="User ID does not match authenticated user")
    return ConversationListResponse(conversations=[ConversationSummary(**c) for c in await asyncio.to_thread(memory.list, actor)])


@router.get("/conversations/{conversation_id}/messages", response_model=ConversationMessagesResponse)
async def get_messages(conversation_id: str, user_id: str = Depends(require_auth),
                       memory: ConversationMemory = Depends(get_memory)):
    try:
        messages = await asyncio.to_thread(memory.messages, conversation_id, user_id)
        return ConversationMessagesResponse(conversation_id=conversation_id, messages=[MessageOut(**m) for m in messages])
    except MemoryNotFound as error:
        raise _memory_error(error) from error


@router.delete("/conversations/{conversation_id}")
async def remove_conversation(conversation_id: str, user_id: str = Depends(require_auth),
                              memory: ConversationMemory = Depends(get_memory)):
    try:
        await asyncio.to_thread(memory.delete, conversation_id, user_id)
        return {"status":"deleted", "conversation_id":conversation_id}
    except MemoryNotFound as error:
        raise _memory_error(error) from error


async def _start_request(request, user_id, memory):
    if request.user_id and request.user_id != user_id:
        raise HTTPException(403, detail="User ID does not match authenticated user")
    try:
        conv_id, turn_id = await asyncio.to_thread(memory.begin_turn, user_id, request.message, request.conversation_id)
        try:
            history = await asyncio.to_thread(memory.context, conv_id, user_id, turn_id)
        except BaseException:
            await asyncio.to_thread(memory.finish_turn, conv_id, user_id, turn_id)
            raise
        return conv_id, turn_id, history
    except (MemoryNotFound, MemoryBusy) as error:
        raise _memory_error(error) from error


@router.post("/chat", response_model=ChatResponse)
async def chat(request: ChatRequest, rag_agent: RAGAgent = Depends(get_rag_agent),
               user_id: str = Depends(require_auth), memory: ConversationMemory = Depends(get_memory),
               _: None = Depends(rate_limit_dependency)):
    conv_id, turn_id, history = await _start_request(request, user_id, memory)
    result = None
    try:
        with trace_attributes(user_id, conv_id):
            result = await asyncio.to_thread(rag_agent.query, user_query=request.message, conversation_history=history, k=6)
        return ChatResponse(answer=result["answer"], sources=result["sources"],
                            reasoning=result.get("reasoning"), conversation_id=conv_id)
    finally:
        await asyncio.to_thread(memory.finish_turn, conv_id, user_id, turn_id,
                                result["answer"] if result else None, result.get("sources") if result else None)


async def generate_chat_stream(message, conversation_history, rag_agent, conversation_id, user_id, turn_id, memory):
    queue: asyncio.Queue = asyncio.Queue(maxsize=64)
    sentinel = object()
    stopped = Event()
    loop = asyncio.get_running_loop()
    full_response, sources, successful = "", [], False

    def send(item):
        from concurrent.futures import TimeoutError
        if stopped.is_set():
            return
        future = asyncio.run_coroutine_threadsafe(queue.put(item), loop)
        while not stopped.is_set():
            try:
                future.result(timeout=1)
                return
            except TimeoutError:
                continue
        future.cancel()

    def worker():
        try:
            with trace_attributes(user_id, conversation_id):
                stream = rag_agent.query_stream(user_query=message, conversation_history=conversation_history, k=6)
                try:
                    for chunk in stream:
                        if stopped.is_set():
                            break
                        send(chunk)
                finally:
                    stream.close()
        except Exception:
            logger.exception("Research stream failed")
            send({"type":"error", "data":"Research generation failed"})
        finally:
            send(sentinel)

    task = None
    try:
        yield f"data: {json.dumps({'type':'conversation_id', 'data':conversation_id})}\n\n"
        task = loop.run_in_executor(None, copy_context().run, worker)
        failed = False
        while True:
            chunk = await queue.get()
            if chunk is sentinel:
                break
            if chunk.get("type") == "content":
                full_response += chunk.get("data", "")
            elif chunk.get("type") == "sources":
                sources = chunk.get("data", [])
            elif chunk.get("type") == "error":
                failed = True
            yield f"data: {json.dumps(chunk)}\n\n"
        await task
        successful = not failed
        yield "data: [DONE]\n\n"
    finally:
        stopped.set()
        await asyncio.shield(asyncio.to_thread(memory.finish_turn, conversation_id, user_id, turn_id,
                                              full_response if successful else None, sources))


@router.post("/chat/stream")
async def chat_stream(request: ChatRequest, rag_agent: RAGAgent = Depends(get_rag_agent),
                      user_id: str = Depends(require_auth), memory: ConversationMemory = Depends(get_memory),
                      _: None = Depends(rate_limit_dependency)):
    conv_id, turn_id, history = await _start_request(request, user_id, memory)
    return StreamingResponse(
        generate_chat_stream(request.message, history, rag_agent, conv_id, user_id, turn_id, memory),
        media_type="text/event-stream", headers={"Cache-Control":"no-cache", "Connection":"keep-alive"},
    )


@router.post("/ingest", response_model=IngestResponse)
async def ingest_arxiv(
    request: IngestRequest,
    vectorstore: VectorStoreService = Depends(get_vectorstore_service),
):
    try:
        from app.scripts.ingest_arxiv import ingest_papers

        result = await asyncio.to_thread(ingest_papers,
            query=request.query,
            max_results=request.max_results,
            vectorstore=vectorstore,
            include_full_text=request.include_full_text,
        )
        return IngestResponse(
            status=result["status"],
            documents_added=result["documents_added"],
            arxiv_ids=result["arxiv_ids"],
            skipped_arxiv_ids=result["skipped_arxiv_ids"],
            errors=result["errors"],
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
