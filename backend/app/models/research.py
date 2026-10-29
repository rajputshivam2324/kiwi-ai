from pydantic import BaseModel, Field
from typing import List, Optional, Dict, Any


class ChatMessage(BaseModel):
    role: str = Field(..., description="Role: 'user' or 'assistant'")
    content: str = Field(..., description="Message content")


class ChatRequest(BaseModel):
    message: str = Field(..., min_length=1, max_length=32000, description="User's question")
    conversation_id: Optional[str] = Field(None, description="Existing conversation ID (omit for new conversation)")
    user_id: Optional[str] = Field(None, description="User ID from Clerk auth")
    conversation_history: List[ChatMessage] = Field(
        default_factory=list,
        description="Previous conversation messages (fallback if no conversation_id)"
    )
    stream: bool = Field(default=False, description="Enable streaming response")


class ChatResponse(BaseModel):
    answer: str = Field(..., description="Generated answer")
    sources: List[Dict[str, Any]] = Field(
        default_factory=list,
        description="Retrieved source documents"
    )
    reasoning: Optional[str] = Field(
        None,
        description="Model's reasoning process (if available)"
    )
    conversation_id: Optional[str] = Field(
        None,
        description="Conversation ID for persistence"
    )


class ArxivDocument(BaseModel):
    arxiv_id: str
    title: str
    authors: List[str]
    abstract: str
    pdf_url: str
    published: str
    categories: List[str]


class IngestRequest(BaseModel):
    query: str = Field(..., min_length=2, max_length=1000, description="arXiv search query")
    max_results: int = Field(default=5, ge=1, le=50, description="Maximum papers to fetch")
    include_full_text: bool = True


class IngestResponse(BaseModel):
    status: str
    documents_added: int
    arxiv_ids: List[str]
    skipped_arxiv_ids: List[str] = Field(default_factory=list)
    errors: List[Dict[str, str]] = Field(default_factory=list)


# ─── Conversation models ─────────────────────────────────────────────

class ConversationCreate(BaseModel):
    user_id: str = Field(..., description="User ID")
    title: str = Field(default="New Research Chat", description="Conversation title")


class ConversationSummary(BaseModel):
    id: str
    title: str
    created_at: str
    updated_at: str
    message_count: int


class ConversationListResponse(BaseModel):
    conversations: List[ConversationSummary]


class MessageOut(BaseModel):
    id: str
    role: str
    content: str
    sources: List[Dict[str, Any]] = Field(default_factory=list)
    created_at: str


class ConversationMessagesResponse(BaseModel):
    conversation_id: str
    messages: List[MessageOut]
