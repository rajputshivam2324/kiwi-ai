import arxiv
import httpx
import logging
import io
import re
from typing import List, Dict, Any, Optional
from pypdf import PdfReader
from app.services.vectorstore import get_vectorstore_service

logger = logging.getLogger(__name__)


class ResearchTools:
    """Collection of research tools for the arXiv chatbot"""
    
    @staticmethod
    def search_arxiv_live(query: str, max_results: int = 5) -> Dict[str, Any]:
        """
        Real-time arXiv search. Returns structured paper metadata.
        Use when user asks about recent papers, trends, or wants to discover papers.
        """
        try:
            logger.info(f"[Tool: search_arxiv_live] query='{query}', max={max_results}")
            
            search = arxiv.Search(
                query=query,
                max_results=max_results,
                sort_by=arxiv.SortCriterion.Relevance
            )
            
            papers = []
            for result in search.results():
                papers.append({
                    "arxiv_id": result.entry_id.split("/")[-1],
                    "title": result.title,
                    "authors": [a.name for a in result.authors[:5]],  # Top 5 authors
                    "abstract": result.summary[:500],  # Truncated abstract
                    "url": f"https://arxiv.org/abs/{result.entry_id.split('/')[-1]}",
                    "pdf_url": str(result.pdf_url),
                    "published": result.published.strftime("%Y-%m-%d"),
                    "categories": result.categories[:3],
                })
            
            return {
                "tool": "search_arxiv_live",
                "success": True,
                "query": query,
                "results_count": len(papers),
                "papers": papers
            }
            
        except Exception as e:
            logger.error(f"[Tool: search_arxiv_live] Error: {e}")
            return {"tool": "search_arxiv_live", "success": False, "error": str(e)}
    
    @staticmethod
    def get_paper_details(arxiv_id: str) -> Dict[str, Any]:
        """
        Fetch detailed metadata for a specific arXiv paper.
        Use when user asks about a specific paper by ID.
        """
        try:
            logger.info(f"[Tool: get_paper_details] arxiv_id='{arxiv_id}'")
            
            # Clean the ID
            arxiv_id = arxiv_id.strip().replace("arxiv:", "").replace("arXiv:", "")
            
            search = arxiv.Search(id_list=[arxiv_id])
            results = list(search.results())
            
            if not results:
                return {"tool": "get_paper_details", "success": False, "error": f"Paper {arxiv_id} not found"}
            
            paper = results[0]
            return {
                "tool": "get_paper_details",
                "success": True,
                "paper": {
                    "arxiv_id": arxiv_id,
                    "title": paper.title,
                    "authors": [a.name for a in paper.authors],
                    "abstract": paper.summary,
                    "url": f"https://arxiv.org/abs/{arxiv_id}",
                    "pdf_url": str(paper.pdf_url),
                    "published": paper.published.strftime("%Y-%m-%d"),
                    "updated": paper.updated.strftime("%Y-%m-%d") if paper.updated else None,
                    "categories": paper.categories,
                    "primary_category": paper.primary_category,
                    "comment": paper.comment,
                    "journal_ref": paper.journal_ref,
                    "doi": paper.doi,
                }
            }
            
        except Exception as e:
            logger.error(f"[Tool: get_paper_details] Error: {e}")
            return {"tool": "get_paper_details", "success": False, "error": str(e)}
    
    @staticmethod
    def summarize_paper(arxiv_id: str) -> Dict[str, Any]:
        """
        Download a paper's PDF and extract key sections for summarization.
        Use when user wants a summary or deeper understanding of a specific paper.
        """
        try:
            logger.info(f"[Tool: summarize_paper] arxiv_id='{arxiv_id}'")
            
            arxiv_id = arxiv_id.strip().replace("arxiv:", "").replace("arXiv:", "")
            pdf_url = f"https://arxiv.org/pdf/{arxiv_id}.pdf"
            
            # Download PDF
            response = httpx.get(pdf_url, timeout=30, follow_redirects=True)
            response.raise_for_status()
            
            reader = PdfReader(io.BytesIO(response.content))
            
            # Extract text from first 8 pages (usually covers intro + methods)
            text_parts = []
            for i, page in enumerate(reader.pages[:8]):
                text_parts.append(page.extract_text())
            
            full_text = "\n\n".join(text_parts)
            
            # Try to extract key sections
            sections = {
                "full_extract": full_text[:6000],  # First ~6000 chars for LLM context
            }
            
            # Try to find abstract boundary
            abstract_match = re.search(r"(?:abstract|Abstract|ABSTRACT)[:\s]*\n?(.*?)(?:\n\s*\n|\n\d+\s+Introduction)", 
                                        full_text, re.DOTALL)
            if abstract_match:
                sections["abstract"] = abstract_match.group(1).strip()[:1500]
            
            return {
                "tool": "summarize_paper",
                "success": True,
                "arxiv_id": arxiv_id,
                "total_pages": len(reader.pages),
                "sections": sections
            }
            
        except Exception as e:
            logger.error(f"[Tool: summarize_paper] Error: {e}")
            return {"tool": "summarize_paper", "success": False, "error": str(e)}
    
    @staticmethod
    def compare_papers(arxiv_ids: List[str]) -> Dict[str, Any]:
        """
        Fetch metadata for multiple papers to enable comparison.
        Use when user wants to compare approaches, methodologies, or results.
        """
        try:
            logger.info(f"[Tool: compare_papers] ids={arxiv_ids}")
            
            clean_ids = [aid.strip().replace("arxiv:", "").replace("arXiv:", "") for aid in arxiv_ids]
            
            search = arxiv.Search(id_list=clean_ids)
            papers = []
            
            for result in search.results():
                aid = result.entry_id.split("/")[-1]
                papers.append({
                    "arxiv_id": aid,
                    "title": result.title,
                    "authors": [a.name for a in result.authors[:5]],
                    "abstract": result.summary,
                    "published": result.published.strftime("%Y-%m-%d"),
                    "categories": result.categories,
                    "url": f"https://arxiv.org/abs/{aid}",
                })
            
            return {
                "tool": "compare_papers",
                "success": True,
                "papers_found": len(papers),
                "papers": papers
            }
            
        except Exception as e:
            logger.error(f"[Tool: compare_papers] Error: {e}")
            return {"tool": "compare_papers", "success": False, "error": str(e)}
    
    @staticmethod
    def search_knowledge_base(query: str, k: int = 5) -> Dict[str, Any]:
        """
        Search the local ChromaDB vector store for previously ingested papers.
        Use when user asks about papers that may have been previously loaded.
        """
        try:
            logger.info(f"[Tool: search_knowledge_base] query='{query}', k={k}")
            
            vectorstore = get_vectorstore_service()
            results = vectorstore.similarity_search(query=query, k=k)
            
            return {
                "tool": "search_knowledge_base",
                "success": True,
                "results_count": len(results),
                "results": results
            }
            
        except Exception as e:
            logger.error(f"[Tool: search_knowledge_base] Error: {e}")
            return {"tool": "search_knowledge_base", "success": False, "error": str(e)}


def analyze_query_for_tools(query: str) -> List[Dict[str, Any]]:
    """
    Analyze a user query and determine which tools to run.
    Returns a list of tool calls to execute.
    """
    query_lower = query.lower().strip()
    tool_calls = []
    
    # Check for specific arXiv IDs in the query
    arxiv_id_pattern = r'\b(\d{4}\.\d{4,5}(?:v\d+)?)\b'
    found_ids = re.findall(arxiv_id_pattern, query)
    
    if found_ids:
        if len(found_ids) > 1:
            # Multiple IDs → compare
            tool_calls.append({
                "tool": "compare_papers",
                "args": {"arxiv_ids": found_ids}
            })
        else:
            # Single ID
            if any(w in query_lower for w in ["summarize", "summary", "explain", "detail", "break down", "overview"]):
                tool_calls.append({
                    "tool": "summarize_paper",
                    "args": {"arxiv_id": found_ids[0]}
                })
            else:
                tool_calls.append({
                    "tool": "get_paper_details",
                    "args": {"arxiv_id": found_ids[0]}
                })
    
    # Check for search intent
    search_signals = [
        "search", "find", "look for", "papers on", "papers about",
        "research on", "recent papers", "latest", "what papers",
        "any papers", "discover", "explore", "show me papers",
        "publications on", "studies on", "work on"
    ]
    
    if any(signal in query_lower for signal in search_signals) or (not found_ids and not tool_calls):
        # Default: search both live arxiv and knowledge base
        # Extract the core search query (remove common filler words)
        search_query = query
        for prefix in ["search for", "find me", "look for", "find", "search"]:
            if query_lower.startswith(prefix):
                search_query = query[len(prefix):].strip()
                break
        
        tool_calls.append({
            "tool": "search_arxiv_live",
            "args": {"query": search_query, "max_results": 5}
        })
        tool_calls.append({
            "tool": "search_knowledge_base",
            "args": {"query": search_query, "k": 3}
        })
    
    return tool_calls


def execute_tools(tool_calls: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    """Execute a list of tool calls and return results"""
    tools = ResearchTools()
    results = []
    
    for call in tool_calls:
        tool_name = call["tool"]
        args = call["args"]
        
        try:
            if tool_name == "search_arxiv_live":
                result = tools.search_arxiv_live(**args)
            elif tool_name == "get_paper_details":
                result = tools.get_paper_details(**args)
            elif tool_name == "summarize_paper":
                result = tools.summarize_paper(**args)
            elif tool_name == "compare_papers":
                result = tools.compare_papers(**args)
            elif tool_name == "search_knowledge_base":
                result = tools.search_knowledge_base(**args)
            else:
                result = {"tool": tool_name, "success": False, "error": f"Unknown tool: {tool_name}"}
            
            results.append(result)
            
        except Exception as e:
            logger.error(f"Error executing tool {tool_name}: {e}")
            results.append({"tool": tool_name, "success": False, "error": str(e)})
    
    return results
