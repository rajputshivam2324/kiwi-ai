import httpx
import logging
import io
import re
from typing import List, Dict, Any

from pypdf import PdfReader

from app.services.research.arxiv_client import (
    clean_arxiv_id,
    extract_search_terms,
    fetch_papers_by_ids,
    search_papers,
)
from app.services.research.vectorstore import get_vectorstore_service

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
            logger.info("[Tool: search_arxiv_live] query=%r, max=%s", query, max_results)
            papers = search_papers(query=query, max_results=max_results)
            for paper in papers:
                paper["abstract"] = paper.get("abstract", "")[:500]

            result = {
                "tool": "search_arxiv_live",
                "success": True,
                "query": query,
                "results_count": len(papers),
                "papers": papers,
            }
            if not papers:
                # Reached arXiv, nothing matched. Distinct from a tool failure —
                # the LLM must not report this as "search errored".
                terms = extract_search_terms(query)
                result["note"] = (
                    "arXiv was reached successfully but returned no matches for "
                    f"terms {terms or '[none extracted]'}. This is not an error — "
                    "ask the user to narrow or rephrase the topic."
                )
                logger.info("[Tool: search_arxiv_live] no matches for terms=%s", terms)
            return result

        except Exception as e:
            logger.error("[Tool: search_arxiv_live] Error: %s", e)
            return {"tool": "search_arxiv_live", "success": False, "error": str(e)}

    @staticmethod
    def get_paper_details(arxiv_id: str) -> Dict[str, Any]:
        """
        Fetch detailed metadata for a specific arXiv paper.
        Use when user asks about a specific paper by ID.
        """
        try:
            logger.info("[Tool: get_paper_details] arxiv_id=%r", arxiv_id)
            arxiv_id = clean_arxiv_id(arxiv_id)
            papers = fetch_papers_by_ids([arxiv_id])

            if not papers:
                return {
                    "tool": "get_paper_details",
                    "success": False,
                    "error": f"Paper {arxiv_id} not found",
                }

            paper = papers[0]
            return {
                "tool": "get_paper_details",
                "success": True,
                "paper": {
                    "arxiv_id": arxiv_id,
                    "title": paper["title"],
                    "authors": paper.get("authors", []),
                    "abstract": paper.get("abstract", ""),
                    "url": paper.get("url", f"https://arxiv.org/abs/{arxiv_id}"),
                    "pdf_url": paper.get("pdf_url", f"https://arxiv.org/pdf/{arxiv_id}.pdf"),
                    "published": paper.get("published", "N/A"),
                    "updated": None,
                    "categories": paper.get("categories", []),
                    "primary_category": paper.get("categories", [None])[0],
                    "comment": None,
                    "journal_ref": None,
                    "doi": None,
                },
            }

        except Exception as e:
            logger.error("[Tool: get_paper_details] Error: %s", e)
            return {"tool": "get_paper_details", "success": False, "error": str(e)}

    @staticmethod
    def summarize_paper(arxiv_id: str) -> Dict[str, Any]:
        """
        Download a paper's PDF and extract key sections for summarization.
        Use when user wants a summary or deeper understanding of a specific paper.
        """
        try:
            logger.info("[Tool: summarize_paper] arxiv_id=%r", arxiv_id)

            arxiv_id = clean_arxiv_id(arxiv_id)
            pdf_url = f"https://arxiv.org/pdf/{arxiv_id}.pdf"

            response = httpx.get(
                pdf_url,
                timeout=30,
                follow_redirects=True,
                headers={"User-Agent": "KiwiAI-Research/1.0"},
            )
            response.raise_for_status()

            reader = PdfReader(io.BytesIO(response.content))

            text_parts = []
            for page in reader.pages[:8]:
                text_parts.append(page.extract_text())

            full_text = "\n\n".join(text_parts)

            sections = {
                "full_extract": full_text[:6000],
            }

            abstract_match = re.search(
                r"(?:abstract|Abstract|ABSTRACT)[:\s]*\n?(.*?)(?:\n\s*\n|\n\d+\s+Introduction)",
                full_text,
                re.DOTALL,
            )
            if abstract_match:
                sections["abstract"] = abstract_match.group(1).strip()[:1500]

            return {
                "tool": "summarize_paper",
                "success": True,
                "arxiv_id": arxiv_id,
                "total_pages": len(reader.pages),
                "sections": sections,
            }

        except Exception as e:
            logger.error("[Tool: summarize_paper] Error: %s", e)
            return {"tool": "summarize_paper", "success": False, "error": str(e)}

    @staticmethod
    def compare_papers(arxiv_ids: List[str]) -> Dict[str, Any]:
        """
        Fetch metadata for multiple papers to enable comparison.
        Use when user wants to compare approaches, methodologies, or results.
        """
        try:
            logger.info("[Tool: compare_papers] ids=%s", arxiv_ids)
            papers = fetch_papers_by_ids(arxiv_ids)
            normalized = []
            for paper in papers:
                normalized.append(
                    {
                        "arxiv_id": paper.get("arxiv_id", ""),
                        "title": paper.get("title", ""),
                        "authors": paper.get("authors", [])[:5],
                        "abstract": paper.get("abstract", ""),
                        "published": paper.get("published", "N/A"),
                        "categories": paper.get("categories", []),
                        "url": paper.get("url", ""),
                    }
                )

            return {
                "tool": "compare_papers",
                "success": True,
                "papers_found": len(normalized),
                "papers": normalized,
            }

        except Exception as e:
            logger.error("[Tool: compare_papers] Error: %s", e)
            return {"tool": "compare_papers", "success": False, "error": str(e)}

    @staticmethod
    def search_knowledge_base(query: str, k: int = 5) -> Dict[str, Any]:
        """
        Search the local ChromaDB vector store for previously ingested papers.
        Use when user asks about papers that may have been previously loaded.
        """
        try:
            logger.info("[Tool: search_knowledge_base] query=%r, k=%s", query, k)

            vectorstore = get_vectorstore_service()
            if vectorstore.get_collection_count() == 0:
                return {
                    "tool": "search_knowledge_base",
                    "success": True,
                    "results_count": 0,
                    "results": [],
                    "note": "Knowledge base is empty — live arXiv search is the primary source.",
                }

            results = vectorstore.similarity_search(query=query, k=k)

            return {
                "tool": "search_knowledge_base",
                "success": True,
                "results_count": len(results),
                "results": results,
            }

        except Exception as e:
            logger.error("[Tool: search_knowledge_base] Error: %s", e)
            return {
                "tool": "search_knowledge_base",
                "success": False,
                "error": str(e),
                "results_count": 0,
                "results": [],
            }


def analyze_query_for_tools(query: str) -> List[Dict[str, Any]]:
    """
    Analyze a user query and determine which tools to run.
    Returns a list of tool calls to execute.
    """
    query_lower = query.lower().strip()
    tool_calls = []

    arxiv_id_pattern = r"\b(\d{4}\.\d{4,5}(?:v\d+)?)\b"
    found_ids = re.findall(arxiv_id_pattern, query)

    if found_ids:
        if len(found_ids) > 1:
            tool_calls.append(
                {
                    "tool": "compare_papers",
                    "args": {"arxiv_ids": found_ids},
                }
            )
        else:
            if any(
                w in query_lower
                for w in [
                    "summarize",
                    "summary",
                    "explain",
                    "detail",
                    "break down",
                    "overview",
                ]
            ):
                tool_calls.append(
                    {
                        "tool": "summarize_paper",
                        "args": {"arxiv_id": found_ids[0]},
                    }
                )
            else:
                tool_calls.append(
                    {
                        "tool": "get_paper_details",
                        "args": {"arxiv_id": found_ids[0]},
                    }
                )

    search_signals = [
        "search",
        "find",
        "look for",
        "papers on",
        "papers about",
        "research on",
        "recent papers",
        "latest",
        "what papers",
        "any papers",
        "discover",
        "explore",
        "show me papers",
        "publications on",
        "studies on",
        "work on",
    ]

    if any(signal in query_lower for signal in search_signals) or (
        not found_ids and not tool_calls
    ):
        search_query = query
        for prefix in ["search for", "find me", "look for", "find", "search"]:
            if query_lower.startswith(prefix):
                search_query = query[len(prefix) :].strip()
                break

        tool_calls.append(
            {
                "tool": "search_arxiv_live",
                "args": {"query": search_query, "max_results": 5},
            }
        )
        tool_calls.append(
            {
                "tool": "search_knowledge_base",
                "args": {"query": search_query, "k": 3},
            }
        )

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
                result = {
                    "tool": tool_name,
                    "success": False,
                    "error": f"Unknown tool: {tool_name}",
                }

            results.append(result)

        except Exception as e:
            logger.error("Error executing tool %s: %s", tool_name, e)
            results.append({"tool": tool_name, "success": False, "error": str(e)})

    return results
