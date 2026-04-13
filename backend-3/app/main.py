from fastapi import FastAPI, HTTPException, Depends, Query
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import StreamingResponse
from app.models import (
    ChatRequest,
    ChatResponse,
    IngestRequest,
    IngestResponse,
    ConversationCreate,
    ConversationListResponse,
    ConversationSummary,
    ConversationMessagesResponse,
    MessageOut,
)
from app.services.rag_agent import get_rag_agent, RAGAgent
from app.services.vectorstore import get_vectorstore_service, VectorStoreService
from app.services.database import (
    init_db,
    close_pool,
    create_conversation,
    list_conversations,
    get_conversation_messages,
    add_message,
    delete_conversation,
    auto_title_conversation,
)
from app.config import get_settings
import logging
import json
import asyncio
from typing import AsyncIterator

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)

# Initialize FastAPI app
app = FastAPI(
    title="arXiv RAG Chatbot API",
    description="Retrieval-Augmented Generation chatbot for arXiv papers with conversation persistence",
    version="2.0.0"
)

# CORS middleware
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],  # Adjust in production
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

settings = get_settings()


@app.on_event("startup")
async def startup_event():
    """Initialize services on startup"""
    logger.info("Starting arXiv RAG Chatbot API v2.0")
    logger.info(f"Model: {settings.model_name}")
    logger.info(f"ChromaDB path: {settings.chroma_db_path}")
    
    # Initialize database tables
    try:
        await init_db()
        logger.info("PostgreSQL database initialized")
    except Exception as e:
        logger.error(f"Failed to initialize database: {e}")
        logger.warning("Continuing without database — conversation persistence will be unavailable")
    
    # Initialize services (singleton pattern)
    vectorstore = get_vectorstore_service()
    logger.info(f"Vector store initialized with {vectorstore.get_collection_count()} documents")
    
    rag_agent = get_rag_agent()
    logger.info("RAG agent initialized with tools")


@app.on_event("shutdown")
async def shutdown_event():
    """Cleanup on shutdown"""
    await close_pool()
    logger.info("Database connection pool closed")


@app.get("/")
async def root():
    """Health check endpoint"""
    return {
        "status": "healthy",
        "service": "arXiv RAG Chatbot",
        "version": "2.0.0"
    }


@app.get("/stats")
async def get_stats(
    vectorstore: VectorStoreService = Depends(get_vectorstore_service)
):
    """Get database statistics"""
    try:
        count = vectorstore.get_collection_count()
        return {
            "total_documents": count,
            "collection_name": settings.collection_name,
            "embedding_model": settings.embedding_model
        }
    except Exception as e:
        logger.error(f"Error fetching stats: {e}")
        raise HTTPException(status_code=500, detail=str(e))


# ─── Conversation CRUD Endpoints ─────────────────────────────────────

@app.post("/conversations")
async def create_new_conversation(request: ConversationCreate):
    """Create a new conversation"""
    try:
        conv_id = await create_conversation(
            user_id=request.user_id,
            title=request.title
        )
        return {"conversation_id": conv_id, "title": request.title}
    except Exception as e:
        logger.error(f"Error creating conversation: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@app.get("/conversations", response_model=ConversationListResponse)
async def get_conversations(user_id: str = Query(..., description="User ID")):
    """List all conversations for a user"""
    try:
        convs = await list_conversations(user_id)
        return ConversationListResponse(
            conversations=[ConversationSummary(**c) for c in convs]
        )
    except Exception as e:
        logger.error(f"Error listing conversations: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@app.get("/conversations/{conversation_id}/messages", response_model=ConversationMessagesResponse)
async def get_messages(conversation_id: str):
    """Get all messages for a conversation"""
    try:
        msgs = await get_conversation_messages(conversation_id)
        return ConversationMessagesResponse(
            conversation_id=conversation_id,
            messages=[MessageOut(**m) for m in msgs]
        )
    except Exception as e:
        logger.error(f"Error fetching messages: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@app.delete("/conversations/{conversation_id}")
async def remove_conversation(conversation_id: str):
    """Delete a conversation and all its messages"""
    try:
        await delete_conversation(conversation_id)
        return {"status": "deleted", "conversation_id": conversation_id}
    except Exception as e:
        logger.error(f"Error deleting conversation: {e}")
        raise HTTPException(status_code=500, detail=str(e))


# ─── Chat Endpoints ──────────────────────────────────────────────────

@app.post("/chat", response_model=ChatResponse)
async def chat(
    request: ChatRequest,
    rag_agent: RAGAgent = Depends(get_rag_agent)
):
    """Non-streaming chat endpoint"""
    try:
        logger.info(f"Received chat request: {request.message[:100]}...")
        
        # Load history from DB if conversation_id provided
        history = []
        if request.conversation_id:
            db_messages = await get_conversation_messages(request.conversation_id)
            history = [{"role": m["role"], "content": m["content"]} for m in db_messages]
        else:
            history = [
                {"role": msg.role, "content": msg.content}
                for msg in request.conversation_history
            ]
        
        # Get response from RAG agent
        result = rag_agent.query(
            user_query=request.message,
            conversation_history=history,
            k=3
        )
        
        # Persist to DB if we have user context
        conv_id = request.conversation_id
        if request.user_id:
            if not conv_id:
                conv_id = await create_conversation(request.user_id)
                await auto_title_conversation(conv_id, request.message)
            
            await add_message(conv_id, "user", request.message)
            await add_message(conv_id, "assistant", result["answer"], result.get("sources"))
        
        return ChatResponse(
            answer=result["answer"],
            sources=result["sources"],
            reasoning=result.get("reasoning"),
            conversation_id=conv_id
        )
        
    except Exception as e:
        logger.error(f"Error in chat endpoint: {e}")
        raise HTTPException(status_code=500, detail=str(e))


async def generate_chat_stream(
    message: str,
    conversation_history: list,
    rag_agent: RAGAgent,
    conversation_id: str = None,
    user_id: str = None,
) -> AsyncIterator[str]:
    """Async generator for streaming chat responses with DB persistence"""
    try:
        # Create conversation if needed
        conv_id = conversation_id
        is_new_conversation = False
        
        if user_id and not conv_id:
            conv_id = await create_conversation(user_id)
            is_new_conversation = True
            logger.info(f"Auto-created conversation {conv_id}")
        
        # Send conversation_id to frontend early
        if conv_id:
            yield f"data: {json.dumps({'type': 'conversation_id', 'data': conv_id})}\n\n"
        
        # Persist user message
        if conv_id:
            await add_message(conv_id, "user", message)
            if is_new_conversation:
                await auto_title_conversation(conv_id, message)
        
        # Stream from RAG agent using a queue to avoid blocking the event loop.
        # rag_agent.query_stream() is a SYNC iterator (LangChain + tool calls),
        # so we run it in a thread and bridge chunks via asyncio.Queue.
        full_response = ""
        sources_data = []
        
        queue: asyncio.Queue = asyncio.Queue()
        _SENTINEL = object()  # marks end of stream
        
        def _run_sync_stream():
            """Runs in a background thread — pushes chunks into the async queue."""
            try:
                for chunk in rag_agent.query_stream(
                    user_query=message,
                    conversation_history=conversation_history,
                    k=3
                ):
                    queue.put_nowait(chunk)
            except Exception as stream_err:
                logger.error(f"RAG stream error in thread: {stream_err}")
                queue.put_nowait({"type": "error", "data": str(stream_err)})
            finally:
                queue.put_nowait(_SENTINEL)
        
        # Start sync iterator in background thread
        loop = asyncio.get_event_loop()
        stream_task = loop.run_in_executor(None, _run_sync_stream)
        
        # Read chunks from the queue without blocking the event loop
        while True:
            chunk = await queue.get()
            if chunk is _SENTINEL:
                break
            
            # Track content for DB persistence
            if chunk.get("type") == "content":
                full_response += chunk.get("data", "")
            elif chunk.get("type") == "sources":
                sources_data = chunk.get("data", [])
            
            # Forward all chunks to client immediately
            yield f"data: {json.dumps(chunk)}\n\n"
        
        # Ensure the background thread has finished
        await stream_task
        
        # Persist assistant response to DB
        if conv_id and full_response:
            # Serialize sources for DB (only metadata, skip large content)
            db_sources = []
            for s in sources_data[:10]:  # Limit sources stored
                meta = s.get("metadata", {})
                db_sources.append({
                    "title": meta.get("title", ""),
                    "arxiv_id": meta.get("arxiv_id", ""),
                    "url": meta.get("url", meta.get("pdf_url", "")),
                })
            await add_message(conv_id, "assistant", full_response, db_sources)
        
        # Send end marker
        yield "data: [DONE]\n\n"
        
    except Exception as e:
        logger.error(f"Error in streaming: {e}")
        error_data = {"type": "error", "data": str(e)}
        yield f"data: {json.dumps(error_data)}\n\n"


@app.post("/chat/stream")
async def chat_stream(
    request: ChatRequest,
    rag_agent: RAGAgent = Depends(get_rag_agent)
):
    """Streaming chat endpoint (Server-Sent Events) with DB persistence"""
    try:
        logger.info(f"Received streaming chat request: {request.message[:100]}...")
        
        # Load history from DB if conversation_id provided
        history = []
        if request.conversation_id:
            db_messages = await get_conversation_messages(request.conversation_id)
            history = [{"role": m["role"], "content": m["content"]} for m in db_messages]
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
            headers={
                "Cache-Control": "no-cache",
                "Connection": "keep-alive",
            }
        )
        
    except Exception as e:
        logger.error(f"Error in streaming chat endpoint: {e}")
        raise HTTPException(status_code=500, detail=str(e))


# ─── Ingest & Admin Endpoints ────────────────────────────────────────

@app.post("/ingest", response_model=IngestResponse)
async def ingest_arxiv(
    request: IngestRequest,
    vectorstore: VectorStoreService = Depends(get_vectorstore_service)
):
    """Ingest arXiv papers into vector store"""
    try:
        from scripts.ingest_arxiv import ingest_papers
        
        logger.info(f"Starting ingestion: query='{request.query}', max_results={request.max_results}")
        
        result = ingest_papers(
            query=request.query,
            max_results=request.max_results,
            vectorstore=vectorstore
        )
        
        return IngestResponse(
            status="success",
            documents_added=result["documents_added"],
            arxiv_ids=result["arxiv_ids"]
        )
        
    except Exception as e:
        logger.error(f"Error in ingest endpoint: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@app.delete("/reset")
async def reset_database(
    vectorstore: VectorStoreService = Depends(get_vectorstore_service)
):
    """Reset the vector database (delete all documents)"""
    try:
        logger.warning("Resetting vector database - all documents will be deleted!")
        vectorstore.reset_collection()
        return {
            "status": "success",
            "message": "Vector database has been reset"
        }
    except Exception as e:
        logger.error(f"Error resetting database: {e}")
        raise HTTPException(status_code=500, detail=str(e))


if __name__ == "__main__":
    import uvicorn
    uvicorn.run(
        "app.main:app",
        host=settings.api_host,
        port=settings.api_port,
        reload=True
    )