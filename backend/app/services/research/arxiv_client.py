"""Reliable arXiv access — Client API with export API HTTP fallback."""

from __future__ import annotations

import logging
import re
import xml.etree.ElementTree as ET
from typing import Any
from urllib.parse import quote

import arxiv
import httpx

logger = logging.getLogger(__name__)

ATOM_NS = {"atom": "http://www.w3.org/2005/Atom", "arxiv": "http://arxiv.org/schemas/atom"}
EXPORT_URL = "https://export.arxiv.org/api/query"
USER_AGENT = "KiwiAI-Research/1.0 (+https://kiwiai.shivamio.in; research@kiwiai.shivamio.in)"

_arxiv_client: arxiv.Client | None = None


def get_arxiv_client() -> arxiv.Client:
    global _arxiv_client
    if _arxiv_client is None:
        _arxiv_client = arxiv.Client(
            page_size=50,
            delay_seconds=3.0,
            num_retries=3,
        )
    return _arxiv_client


def clean_arxiv_id(arxiv_id: str) -> str:
    return arxiv_id.strip().replace("arxiv:", "").replace("arXiv:", "")


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


def _search_export_api(query: str, max_results: int) -> list[dict[str, Any]]:
    # export API uses Lucene-style query syntax
    search_query = quote(f"all:{query}")
    url = (
        f"{EXPORT_URL}?search_query={search_query}"
        f"&start=0&max_results={max_results}"
        f"&sortBy=relevance&sortOrder=descending"
    )
    response = httpx.get(
        url,
        timeout=30.0,
        follow_redirects=True,
        headers={"User-Agent": USER_AGENT},
    )
    response.raise_for_status()
    return _parse_export_atom(response.text)


def _fetch_export_by_ids(arxiv_ids: list[str]) -> list[dict[str, Any]]:
    if not arxiv_ids:
        return []
    id_list = ",".join(clean_arxiv_id(aid) for aid in arxiv_ids)
    url = f"{EXPORT_URL}?id_list={quote(id_list)}"
    response = httpx.get(
        url,
        timeout=30.0,
        follow_redirects=True,
        headers={"User-Agent": USER_AGENT},
    )
    response.raise_for_status()
    return _parse_export_atom(response.text)


def search_papers(query: str, max_results: int = 5) -> list[dict[str, Any]]:
    """Search arXiv by query. Tries Client API first, then export HTTP API."""
    errors: list[str] = []

    try:
        client = get_arxiv_client()
        search = arxiv.Search(
            query=query,
            max_results=max_results,
            sort_by=arxiv.SortCriterion.Relevance,
        )
        papers = [_paper_from_result(r) for r in client.results(search)]
        if papers:
            logger.info("arxiv Client returned %s papers for %r", len(papers), query[:80])
            return papers
    except Exception as e:
        msg = f"arxiv Client failed: {e}"
        logger.warning(msg)
        errors.append(msg)

    try:
        papers = _search_export_api(query, max_results)
        if papers:
            logger.info("arxiv export API returned %s papers for %r", len(papers), query[:80])
            return papers
        errors.append("export API returned no papers")
    except Exception as e:
        msg = f"arxiv export API failed: {e}"
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
        client = get_arxiv_client()
        search = arxiv.Search(id_list=clean_ids)
        papers = [_paper_from_result(r) for r in client.results(search)]
        if papers:
            return papers
    except Exception as e:
        msg = f"arxiv Client id lookup failed: {e}"
        logger.warning(msg)
        errors.append(msg)

    try:
        papers = _fetch_export_by_ids(clean_ids)
        if papers:
            return papers
        errors.append("export API returned no papers for ids")
    except Exception as e:
        msg = f"arxiv export id lookup failed: {e}"
        logger.warning(msg)
        errors.append(msg)

    raise RuntimeError("; ".join(errors) or "arXiv id lookup failed")
