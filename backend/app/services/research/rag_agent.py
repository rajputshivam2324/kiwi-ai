from app.services.research.prompts import SYSTEM_PROMPT
from app.services.research.llm_service import get_llm_service
from app.services.research.vectorstore import get_vectorstore_service
from app.services.research.tools import analyze_query_for_tools, execute_tools
from typing import List, Dict, Any, Iterator
import json
import logging

logger = logging.getLogger(__name__)


class RAGAgent:
    def __init__(self):
        self.llm_service = get_llm_service()
        self.vectorstore = get_vectorstore_service()
    
    @staticmethod
    def _make_arxiv_url(metadata: Dict[str, Any]) -> str:
        """Build canonical https://arxiv.org/abs/ URL from metadata. Always prefer arxiv_id."""
        arxiv_id = metadata.get("arxiv_id", "").strip()
        # Strip version suffix like v1, v2 for canonical URL
        if arxiv_id:
            base_id = arxiv_id.split("v")[0] if "v" in arxiv_id else arxiv_id
            return f"https://arxiv.org/abs/{base_id}"
        # Fall back to pdf_url converted to abs URL
        pdf_url = metadata.get("pdf_url", "") or metadata.get("url", "")
        if pdf_url and "arxiv.org" in pdf_url:
            # Convert pdf URL to abs URL
            return pdf_url.replace("/pdf/", "/abs/").replace(".pdf", "")
        return ""

    def _format_context(self, documents: List[Dict[str, Any]], seen_ids: set = None) -> str:
        """Format retrieved documents into context string with explicit URLs for the LLM"""
        if not documents:
            return "_No documents found in local knowledge base._"
        
        if seen_ids is None:
            seen_ids = set()

        context_parts = []
        paper_num = 1

        for doc in documents:
            metadata = doc.get("metadata", {})
            content = doc.get("content", "")
            arxiv_id = metadata.get("arxiv_id", "").strip()
            title = metadata.get("title", "Untitled")

            # Skip duplicate chunks from the same paper
            key = arxiv_id if arxiv_id else title
            if key in seen_ids:
                continue
            seen_ids.add(key)

            url = self._make_arxiv_url(metadata)
            url_line = f"- **CITE URL** (use exactly): {url}" if url else "- **URL**: Not available"

            context_parts.append(
                f"[Paper {paper_num}]\n"
                f"- **Title**: {title}\n"
                f"- **Authors**: {metadata.get('authors', 'N/A')}\n"
                f"- **arXiv ID**: {arxiv_id or 'N/A'}\n"
                f"- **Published**: {metadata.get('published', 'N/A')}\n"
                f"{url_line}\n"
                f"- **Excerpt**: {content[:800]}\n"
            )
            paper_num += 1

        return "\n---\n".join(context_parts) if context_parts else "_No unique documents found._"
    
    def _format_tool_results(self, tool_results: List[Dict[str, Any]]) -> str:
        """Format tool results into readable context for the LLM"""
        if not tool_results:
            return "_No tools were invoked._"
        
        parts = []
        for result in tool_results:
            tool_name = result.get("tool", "unknown")
            success = result.get("success", False)
            
            if not success:
                parts.append(f"**{tool_name}**: ⚠️ Failed — {result.get('error', 'Unknown error')}")
                continue
            
            if tool_name == "search_arxiv_live":
                papers = result.get("papers", [])
                if papers:
                    lines = [f"**Live arXiv Search** — Found {len(papers)} papers for '{result.get('query', '')}':\n"]
                    for p in papers:
                        authors_str = ", ".join(p.get("authors", [])[:3])
                        aid = p.get('arxiv_id', '')
                        cite_url = f"https://arxiv.org/abs/{aid}" if aid else p.get('url', '')
                        lines.append(
                            f"- **{p['title']}** by *{authors_str}* ({p['published']})\n"
                            f"  **CITE URL** (use exactly): {cite_url}\n"
                            f"  {p['abstract'][:200]}...\n"
                        )
                    parts.append("\n".join(lines))
                else:
                    note = result.get("note") or "No papers matched."
                    parts.append(
                        f"**Live arXiv Search**: No papers found for "
                        f"'{result.get('query', '')}'. {note}"
                    )
            
            elif tool_name == "get_paper_details":
                p = result.get("paper", {})
                if p:
                    aid = p.get('arxiv_id', '')
                    cite_url = f"https://arxiv.org/abs/{aid}" if aid else p.get('url', '')
                    parts.append(
                        f"**Paper Details — {p['title']}**\n"
                        f"- **Authors**: {', '.join(p.get('authors', []))}\n"
                        f"- **Published**: {p.get('published', 'N/A')}\n"
                        f"- **Categories**: {', '.join(p.get('categories', []))}\n"
                        f"- **CITE URL** (use exactly): {cite_url}\n"
                        f"- **Abstract**: {p.get('abstract', 'N/A')}\n"
                    )
            
            elif tool_name == "summarize_paper":
                sections = result.get("sections", {})
                parts.append(
                    f"**Paper Summary — arXiv:{result.get('arxiv_id', '?')}** "
                    f"({result.get('total_pages', '?')} pages)\n\n"
                    f"{sections.get('full_extract', 'No text extracted.')[:4000]}"
                )
            
            elif tool_name == "compare_papers":
                papers = result.get("papers", [])
                if papers:
                    lines = [f"**Paper Comparison** — {len(papers)} papers:\n"]
                    for p in papers:
                        aid = p.get('arxiv_id', '')
                        cite_url = f"https://arxiv.org/abs/{aid}" if aid else p.get('url', '')
                        lines.append(
                            f"### {p['title']}\n"
                            f"- **Authors**: {', '.join(p.get('authors', [])[:3])}\n"
                            f"- **Published**: {p['published']}\n"
                            f"- **CITE URL** (use exactly): {cite_url}\n"
                            f"- **Abstract**: {p['abstract'][:300]}...\n"
                        )
                    parts.append("\n".join(lines))
            
            elif tool_name == "search_knowledge_base":
                kb_results = result.get("results", [])
                note = result.get("note")
                if kb_results:
                    lines = [f"**Knowledge Base** — {len(kb_results)} relevant chunks:\n"]
                    for r in kb_results:
                        meta = r.get("metadata", {})
                        aid = meta.get("arxiv_id", "")
                        cite_url = f"https://arxiv.org/abs/{aid}" if aid else ""
                        url_line = f" | **CITE URL**: {cite_url}" if cite_url else ""
                        lines.append(
                            f"- **{meta.get('title', 'N/A')}** (arXiv:{aid}){url_line}:\n"
                            f"  {r.get('content', '')[:200]}..."
                        )
                    parts.append("\n".join(lines))
                elif note:
                    parts.append(f"**Knowledge Base**: {note}")
                elif result.get("success"):
                    parts.append("**Knowledge Base**: No matching ingested papers (live arXiv results above are authoritative).")
        
        return "\n\n---\n\n".join(parts)
    
    def _build_messages(
        self,
        query: str,
        context: str,
        tool_results_str: str,
        conversation_history: List[Dict[str, str]] = None
    ) -> List[Dict[str, str]]:
        """Build message list for LLM"""
        messages = []
        
        # Add system prompt with context and tool results
        messages.append({
            "role": "system",
            "content": SYSTEM_PROMPT.format(
                context=context,
                tool_results=tool_results_str
            )
        })
        
        # Add conversation history if provided
        if conversation_history:
            for msg in conversation_history:
                messages.append({
                    "role": msg.get("role", "user"),
                    "content": msg.get("content", "")
                })
        
        # Add current query
        messages.append({
            "role": "user",
            "content": query
        })
        
        return messages
    
    def _retrieve_documents(self, user_query: str, k: int) -> list[dict[str, Any]]:
        """Retrieve from knowledge base; never fail the whole query on Chroma errors."""
        try:
            return self.vectorstore.similarity_search(query=user_query, k=k)
        except Exception as e:
            logger.warning("Knowledge base retrieval failed (continuing with live arXiv): %s", e)
            return []

    def query(
        self,
        user_query: str,
        conversation_history: List[Dict[str, str]] = None,
        k: int = 3
    ) -> Dict[str, Any]:
        """Non-streaming RAG query with tools"""
        try:
            # 1. Analyze query and run tools
            logger.info(f"Analyzing query for tools: {user_query[:80]}")
            tool_calls = analyze_query_for_tools(user_query)
            tool_results = execute_tools(tool_calls) if tool_calls else []
            tool_results_str = self._format_tool_results(tool_results)
            
            # 2. Retrieve from knowledge base
            logger.info(f"Retrieving documents for query: {user_query}")
            retrieved_docs = self._retrieve_documents(user_query, k)
            context = self._format_context(retrieved_docs)
            
            # 3. Build messages
            messages = self._build_messages(
                query=user_query,
                context=context,
                tool_results_str=tool_results_str,
                conversation_history=conversation_history
            )
            
            # 4. Get LLM response
            logger.info("Generating response from LLM")
            llm_response = self.llm_service.invoke(messages)
            
            # Collect, normalize & deduplicate sources
            sources = []
            seen_ids = set()
            
            def _norm(src):
                meta = src.get("metadata", {})
                # Always use canonical arxiv.org/abs/ URL — overwrite even if url exists
                url = self._make_arxiv_url(meta)
                if url:
                    meta["url"] = url
                elif not meta.get("url"):
                    meta["url"] = "#"
                src["metadata"] = meta
                return src
            
            for doc in retrieved_docs:
                doc = _norm(doc)
                key = (doc.get("metadata", {}).get("arxiv_id", "") or doc.get("metadata", {}).get("title", str(len(seen_ids)))).strip()
                if key not in seen_ids:
                    seen_ids.add(key)
                    sources.append(doc)
            
            for tr in tool_results:
                if tr.get("tool") == "search_arxiv_live" and tr.get("papers"):
                    for p in tr["papers"]:
                        key = (p.get("arxiv_id", "") or p.get("title", str(len(seen_ids)))).strip()
                        if key not in seen_ids:
                            seen_ids.add(key)
                            sources.append(_norm({"content": p.get("abstract", ""), "metadata": p, "score": 0}))
            
            return {
                "answer": llm_response["content"],
                "sources": sources,
                "reasoning": llm_response.get("reasoning")
            }
            
        except Exception as e:
            logger.error(f"Error in RAG query: {e}")
            raise
    
    def query_stream(
        self,
        user_query: str,
        conversation_history: List[Dict[str, str]] = None,
        k: int = 3
    ) -> Iterator[Dict[str, Any]]:
        """Streaming RAG query with tools"""
        try:
            # 1. Yield status: running tools
            yield {"type": "status", "data": "Searching research databases..."}
            
            # 2. Analyze query and run tools
            logger.info(f"Analyzing query for tools: {user_query[:80]}")
            tool_calls = analyze_query_for_tools(user_query)
            tool_results = execute_tools(tool_calls) if tool_calls else []
            tool_results_str = self._format_tool_results(tool_results)
            
            # 3. Yield tool results metadata. Failures are surfaced too —
            # silently dropping them is why a broken arXiv search looked like
            # the model "choosing" not to cite papers.
            for tr in tool_results:
                if tr.get("success"):
                    summary = self._get_tool_summary(tr)
                else:
                    summary = f"Failed: {tr.get('error', 'unknown error')}"
                    logger.error(
                        "Tool %s failed: %s", tr.get("tool"), tr.get("error")
                    )
                yield {"type": "tool_result", "data": {
                    "tool": tr.get("tool"),
                    "success": bool(tr.get("success")),
                    "summary": summary,
                }}
            
            # 4. Retrieve from knowledge base
            yield {"type": "status", "data": "Analyzing relevant papers..."}
            retrieved_docs = self._retrieve_documents(user_query, k)
            
            # 5. Collect, normalize & deduplicate sources
            all_sources = []
            seen_ids: set = set()  # Track by arxiv_id to avoid duplicates
            
            def _normalize_source(src: Dict[str, Any]) -> Dict[str, Any]:
                """Ensure every source has a strict https://arxiv.org/abs/ URL"""
                meta = src.get("metadata", {})
                url = self._make_arxiv_url(meta)
                if url:
                    meta["url"] = url
                elif not meta.get("url"):
                    meta["url"] = "#"
                src["metadata"] = meta
                return src
            
            # Add ChromaDB results (deduplicated)
            for doc in retrieved_docs:
                doc = _normalize_source(doc)
                aid = doc.get("metadata", {}).get("arxiv_id", "").strip()
                key = aid if aid else doc.get("metadata", {}).get("title", str(len(seen_ids)))
                if key not in seen_ids:
                    seen_ids.add(key)
                    all_sources.append(doc)
            
            # Now build context using same seen_ids set (so no double-counting chunks)
            context = self._format_context(retrieved_docs, seen_ids=set())
            
            # Add live arxiv search results (deduplicated)
            for tr in tool_results:
                if tr.get("tool") == "search_arxiv_live" and tr.get("papers"):
                    for p in tr["papers"]:
                        aid = p.get("arxiv_id", "")
                        key = aid if aid else p.get("title", str(len(seen_ids)))
                        if key not in seen_ids:
                            seen_ids.add(key)
                            source = _normalize_source({
                                "content": p.get("abstract", ""),
                                "metadata": p,
                                "score": 0
                            })
                            all_sources.append(source)
            
            yield {"type": "sources", "data": all_sources}
            
            # 6. Build messages
            messages = self._build_messages(
                query=user_query,
                context=context,
                tool_results_str=tool_results_str,
                conversation_history=conversation_history
            )
            
            # 7. Stream LLM response
            yield {"type": "status", "data": "Generating response..."}
            
            try:
                chunk_count = 0
                for chunk in self.llm_service.stream(messages):
                    chunk_count += 1
                    yield chunk
                logger.info(f"LLM stream completed with {chunk_count} content chunks")
            except Exception as llm_err:
                logger.error(f"LLM streaming failed: {llm_err}")
                yield {"type": "error", "data": f"LLM streaming error: {str(llm_err)}"}
                
        except Exception as e:
            logger.error(f"Error in streaming RAG query: {e}")
            yield {"type": "error", "data": str(e)}
    
    def _get_tool_summary(self, tool_result: Dict[str, Any]) -> str:
        """Get a short human-readable summary of a tool result"""
        tool = tool_result.get("tool", "")
        if tool == "search_arxiv_live":
            count = tool_result.get("results_count", 0)
            return f"Found {count} papers on arXiv"
        elif tool == "get_paper_details":
            title = tool_result.get("paper", {}).get("title", "")
            return f"Retrieved: {title[:60]}"
        elif tool == "summarize_paper":
            pages = tool_result.get("total_pages", 0)
            return f"Extracted {pages}-page paper"
        elif tool == "compare_papers":
            count = tool_result.get("papers_found", 0)
            return f"Comparing {count} papers"
        elif tool == "search_knowledge_base":
            count = tool_result.get("results_count", 0)
            return f"Found {count} results in knowledge base"
        return tool


# Singleton instance
_rag_agent = None

def get_rag_agent() -> RAGAgent:
    global _rag_agent
    if _rag_agent is None:
        _rag_agent = RAGAgent()
    return _rag_agent