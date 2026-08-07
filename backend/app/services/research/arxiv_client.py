"""Reliable arXiv access — export HTTP API first, arxiv Client as fallback."""

from __future__ import annotations

import logging
import re
import socket
import xml.etree.ElementTree as ET
from typing import Any
from urllib.parse import quote

import arxiv
import httpx

logger = logging.getLogger(__name__)

ATOM_NS = {"atom": "http://www.w3.org/2005/Atom", "arxiv": "http://arxiv.org/schemas/atom"}
EXPORT_URLS = (
    "https://export.arxiv.org/api/query",
    "http://export.arxiv.org/api/query",
)
USER_AGENT = "KiwiAI-Research/1.0 (+https://kiwiai.shivamio.in; research@kiwiai.shivamio.in)"

_arxiv_client: arxiv.Client | None = None
_http_client: httpx.Client | None = None


def get_http_client() -> httpx.Client:
    global _http_client
    if _http_client is None:
        # Prefer IPv4 — some EC2/Docker setups have broken IPv6 egress
        transport = httpx.HTTPTransport(local_address="0.0.0.0")
        _http_client = httpx.Client(
            timeout=httpx.Timeout(connect=10.0, read=30.0, write=10.0, pool=10.0),
            follow_redirects=True,
            headers={"User-Agent": USER_AGENT},
            transport=transport,
        )
    return _http_client


def get_arxiv_client() -> arxiv.Client:
    global _arxiv_client
    if _arxiv_client is None:
        _arxiv_client = arxiv.Client(
            page_size=50,
            delay_seconds=1.0,
            num_retries=2,
        )
    return _arxiv_client


def clean_arxiv_id(arxiv_id: str) -> str:
    return arxiv_id.strip().replace("arxiv:", "").replace("arXiv:", "")


def sanitize_search_query(query: str) -> str:
    """Strip Lucene-special characters; keep words for arXiv search."""
    cleaned = re.sub(r"[^\w\s\-]", " ", query, flags=re.UNICODE)
    cleaned = re.sub(r"\s+", " ", cleaned).strip()
    return cleaned or query.strip()


def _paper_from_result(result: arxiv.Result) -> dict[str, Any]:
    arxiv_id = result.entry_id.split("/")[-1]
    return {
        "arxiv_id": arxiv_id,
        "title": result.title.strip(),
        "authors": [a.name for a in result.authors[:5]],
        "abstract": result.summary.strip(),
        "url": f"https://arxiv.org/abs/{arxiv_id}",
        "pdf_url": str(result.pdf_url),
        "published": result.published.strftime("%Y-%m-%d"),
        "categories": result.categories[:3],
    }


def _parse_export_atom(xml_text: str) -> list[dict[str, Any]]:
    root = ET.fromstring(xml_text)
    papers: list[dict[str, Any]] = []

    for entry in root.findall("atom:entry", ATOM_NS):
        raw_id = (entry.findtext("atom:id", default="", namespaces=ATOM_NS) or "").strip()
        arxiv_id = raw_id.rsplit("/", 1)[-1] if raw_id else ""
        title = (entry.findtext("atom:title", default="", namespaces=ATOM_NS) or "").strip()
        summary = (entry.findtext("atom:summary", default="", namespaces=ATOM_NS) or "").strip()
        published = (entry.findtext("atom:published", default="", namespaces=ATOM_NS) or "")[:10]
        authors = [
            (author.findtext("atom:name", default="", namespaces=ATOM_NS) or "").strip()
            for author in entry.findall("atom:author", ATOM_NS)
        ]
        categories = [
            cat.attrib.get("term", "")
            for cat in entry.findall("atom:category", ATOM_NS)
            if cat.attrib.get("term")
        ]
        if not arxiv_id:
            continue
        papers.append(
            {
                "arxiv_id": arxiv_id,
                "title": re.sub(r"\s+", " ", title),
                "authors": [a for a in authors if a][:5],
                "abstract": re.sub(r"\s+", " ", summary),
                "url": f"https://arxiv.org/abs/{arxiv_id}",
                "pdf_url": f"https://arxiv.org/pdf/{arxiv_id}.pdf",
                "published": published or "N/A",
                "categories": categories[:3],
            }
        )
    return papers


def _http_get_export(url: str) -> str:
    client = get_http_client()
    response = client.get(url)
    response.raise_for_status()
    return response.text


def _search_export_api(query: str, max_results: int) -> list[dict[str, Any]]:
    safe_query = sanitize_search_query(query)
    # Quote multi-word terms for Lucene
    terms = safe_query.split()
    if len(terms) > 1:
        lucene = " AND ".join(f'all:"{t}"' if len(t) > 2 else f"all:{t}" for t in terms[:8])
    else:
        lucene = f'all:"{safe_query}"' if safe_query else "all:RAG"

    encoded = quote(lucene, safe="")
    errors: list[str] = []

    for base in EXPORT_URLS:
        url = (
            f"{base}?search_query={encoded}"
            f"&start=0&max_results={max_results}"
            f"&sortBy=relevance&sortOrder=descending"
        )
        try:
            xml_text = _http_get_export(url)
            papers = _parse_export_atom(xml_text)
            if papers:
                return papers
            errors.append(f"{base}: no papers")
        except Exception as e:
            errors.append(f"{base}: {e}")

    if errors:
        raise RuntimeError("; ".join(errors))
    return []


def _fetch_export_by_ids(arxiv_ids: list[str]) -> list[dict[str, Any]]:
    if not arxiv_ids:
        return []
    id_list = ",".join(clean_arxiv_id(aid) for aid in arxiv_ids)
    encoded_ids = quote(id_list, safe=",")
    errors: list[str] = []

    for base in EXPORT_URLS:
        url = f"{base}?id_list={encoded_ids}"
        try:
            xml_text = _http_get_export(url)
            papers = _parse_export_atom(xml_text)
            if papers:
                return papers
            errors.append(f"{base}: no papers for ids")
        except Exception as e:
            errors.append(f"{base}: {e}")

    raise RuntimeError("; ".join(errors))


def _search_client_api(query: str, max_results: int) -> list[dict[str, Any]]:
    client = get_arxiv_client()
    search = arxiv.Search(
        query=sanitize_search_query(query),
        max_results=max_results,
        sort_by=arxiv.SortCriterion.Relevance,
    )
    return [_paper_from_result(r) for r in client.results(search)]


def search_papers(query: str, max_results: int = 5) -> list[dict[str, Any]]:
    """Search arXiv — export HTTP API first (works best in Docker/EC2), Client as fallback."""
    errors: list[str] = []

    try:
        papers = _search_export_api(query, max_results)
        if papers:
            logger.info("arxiv export API returned %s papers for %r", len(papers), query[:80])
            return papers
    except Exception as e:
        msg = f"export API failed: {e}"
        logger.warning(msg)
        errors.append(msg)

    try:
        papers = _search_client_api(query, max_results)
        if papers:
            logger.info("arxiv Client returned %s papers for %r", len(papers), query[:80])
            return papers
        errors.append("arxiv Client returned no papers")
    except Exception as e:
        msg = f"arxiv Client failed: {e}"
        logger.warning(msg)
        errors.append(msg)

    raise RuntimeError("; ".join(errors) or "arXiv search failed")


def fetch_papers_by_ids(arxiv_ids: list[str]) -> list[dict[str, Any]]:
    """Fetch paper metadata by arXiv ID(s)."""
    clean_ids = [clean_arxiv_id(aid) for aid in arxiv_ids if aid.strip()]
    if not clean_ids:
        return []

    errors: list[str] = []

    try:
        papers = _fetch_export_by_ids(clean_ids)
        if papers:
            return papers
    except Exception as e:
        errors.append(f"export id lookup: {e}")

    try:
        papers = _search_client_api_by_ids(clean_ids)
        if papers:
            return papers
    except Exception as e:
        errors.append(f"client id lookup: {e}")

    raise RuntimeError("; ".join(errors) or "arXiv id lookup failed")


def _search_client_api_by_ids(arxiv_ids: list[str]) -> list[dict[str, Any]]:
    client = get_arxiv_client()
    search = arxiv.Search(id_list=arxiv_ids)
    return [_paper_from_result(r) for r in client.results(search)]


def connectivity_check() -> dict[str, Any]:
    """Diagnostics for production — DNS + HTTP reachability to arXiv export API."""
    result: dict[str, Any] = {
        "dns_export_arxiv_org": None,
        "http_export_ok": False,
        "search_ok": False,
        "sample_title": None,
        "errors": [],
    }

    try:
        socket.getaddrinfo("export.arxiv.org", 443, type=socket.SOCK_STREAM)
        result["dns_export_arxiv_org"] = True
    except OSError as e:
        result["dns_export_arxiv_org"] = False
        result["errors"].append(f"DNS: {e}")

    try:
        _http_get_export(f"{EXPORT_URLS[0]}?search_query=all:RAG&max_results=1")
        result["http_export_ok"] = True
    except Exception as e:
        result["errors"].append(f"HTTP: {e}")

    try:
        papers = search_papers("retrieval augmented generation", max_results=1)
        result["search_ok"] = True
        if papers:
            result["sample_title"] = papers[0].get("title")
    except Exception as e:
        result["errors"].append(f"Search: {e}")

    return result
