"""Reliable arXiv access — export HTTP API first, arxiv Client as fallback.

Query building matters more than transport here. arXiv's ``search_query`` is a
Lucene-style expression: joining every word of a natural-language question with
``AND`` makes conversational filler ("what are the latest papers about ...")
a *required* term, which reliably returns zero results. So we strip filler,
then walk a relaxation ladder from most precise to broadest and take the first
step that matches.

The other important distinction: "arXiv answered, nothing matched" is an empty
result, not an error. Only genuine transport failures raise.
"""

from __future__ import annotations

import logging
import os
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
# arXiv's API terms of use ask for a descriptive, contactable User-Agent.
USER_AGENT = "KiwiAI-Research/1.0 (+https://kiwiai.shivamio.in; research@kiwiai.shivamio.in)"

# Some EC2/Docker networks advertise IPv6 without working egress. Binding the
# source socket to 0.0.0.0 forces IPv4. Set ARXIV_FORCE_IPV4=0 to disable.
_FORCE_IPV4 = os.getenv("ARXIV_FORCE_IPV4", "1").strip().lower() not in {"0", "false", "no"}

# How many content terms to keep. arXiv AND-queries get brittle beyond ~6.
_MAX_TERMS = 6

# Conversational filler plus words that describe the *request* rather than the
# subject. Stripping these is what makes AND-joined queries viable.
_STOPWORDS = frozenset(
    """
    a an the and or of on in to for with from by at as is are was were be been being
    do does did what which who whom whose when where how why if then than that this
    these those there their them they it its he she we us you your my me i our
    any some all more most much many few several other another same such only just
    please give show tell list find finding found searching search look looking see
    discover explore summarize summarise summary explain overview describe compare
    comparison contrast between versus vs about regarding concerning involving
    related relating recent recently latest newest new current currently
    paper papers article articles arxiv preprint preprints publication publications
    research researches study studies work works literature review reviews survey
    can could would should may might must have has had will shall need needs want
    wants get gets got let lets good better best top great nice cool interesting
    important useful relevant available known
    """.split()
)


_arxiv_client: arxiv.Client | None = None
_http_client: httpx.Client | None = None
_plain_http_client: httpx.Client | None = None

_TIMEOUT = httpx.Timeout(connect=10.0, read=30.0, write=10.0, pool=10.0)


def _new_http_client(force_ipv4: bool) -> httpx.Client:
    kwargs: dict[str, Any] = {
        "timeout": _TIMEOUT,
        "follow_redirects": True,
        "headers": {"User-Agent": USER_AGENT},
    }
    if force_ipv4:
        kwargs["transport"] = httpx.HTTPTransport(local_address="0.0.0.0", retries=1)
    return httpx.Client(**kwargs)


def get_http_client() -> httpx.Client:
    global _http_client
    if _http_client is None:
        _http_client = _new_http_client(force_ipv4=_FORCE_IPV4)
    return _http_client


def _get_plain_http_client() -> httpx.Client:
    """Unbound client used to retry when the IPv4-bound socket cannot connect."""
    global _plain_http_client
    if _plain_http_client is None:
        _plain_http_client = _new_http_client(force_ipv4=False)
    return _plain_http_client


def get_arxiv_client() -> arxiv.Client:
    global _arxiv_client
    if _arxiv_client is None:
        # arXiv asks for >=3s between requests; being polite avoids 429s from
        # shared datacenter IPs, which is what EC2 looks like to them.
        _arxiv_client = arxiv.Client(page_size=50, delay_seconds=3.0, num_retries=3)
    return _arxiv_client


def clean_arxiv_id(arxiv_id: str) -> str:
    return arxiv_id.strip().replace("arxiv:", "").replace("arXiv:", "")


def sanitize_search_query(query: str) -> str:
    """Strip Lucene-special characters; keep words for arXiv search."""
    cleaned = re.sub(r"[^\w\s\-]", " ", query, flags=re.UNICODE)
    cleaned = re.sub(r"\s+", " ", cleaned).strip()
    return cleaned or query.strip()


def extract_search_terms(query: str, limit: int = _MAX_TERMS) -> list[str]:
    """Content-bearing terms from a natural-language query, order preserved.

    >>> extract_search_terms("what are the latest papers about mixture of experts")
    ['mixture', 'experts']
    """
    words = sanitize_search_query(query).lower().split()
    terms: list[str] = []
    for word in words:
        stripped = word.strip("-")
        if len(stripped) < 2 or stripped in _STOPWORDS:
            continue
        if stripped not in terms:
            terms.append(stripped)
    return terms[:limit]


def build_query_ladder(query: str) -> list[str]:
    """Lucene queries from most precise to broadest. First non-empty hit wins."""
    terms = extract_search_terms(query)
    if not terms:
        return []

    if len(terms) == 1:
        return [f'all:"{terms[0]}"']

    ladder = [
        # 1. exact phrase — highest precision
        'all:"{0}"'.format(" ".join(terms)),
        # 2. every term must appear, anywhere
        " AND ".join(f'all:"{t}"' for t in terms),
    ]
    if len(terms) > 2:
        # 3. any term — broad, but still topical and never empty in practice
        ladder.append(" OR ".join(f'all:"{t}"' for t in terms))
    return ladder


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
    """GET with one retry on an unbound socket if the IPv4-bound one can't connect."""
    try:
        response = get_http_client().get(url)
        response.raise_for_status()
        return response.text
    except (httpx.ConnectError, httpx.ConnectTimeout) as e:
        if not _FORCE_IPV4:
            raise
        logger.warning("arXiv connect failed on IPv4-bound socket (%s); retrying unbound", e)
        response = _get_plain_http_client().get(url)
        response.raise_for_status()
        return response.text


def _export_search_url(lucene: str, max_results: int, base: str) -> str:
    return (
        f"{base}?search_query={quote(lucene, safe='')}"
        f"&start=0&max_results={max_results}"
        f"&sortBy=relevance&sortOrder=descending"
    )


def _search_export_api(query: str, max_results: int) -> list[dict[str, Any]]:
    """Walk the query ladder against the export API.

    Returns [] when arXiv responded but nothing matched. Raises RuntimeError
    only when no mirror could be reached at all.
    """
    ladder = build_query_ladder(query)
    if not ladder:
        logger.info("No searchable terms in %r — skipping arXiv search", query[:80])
        return []

    transport_errors: list[str] = []
    reached = False

    for lucene in ladder:
        for base in EXPORT_URLS:
            try:
                xml_text = _http_get_export(_export_search_url(lucene, max_results, base))
            except Exception as e:
                transport_errors.append(f"{base}: {e}")
                continue

            reached = True
            try:
                papers = _parse_export_atom(xml_text)
            except ET.ParseError as e:
                transport_errors.append(f"{base}: malformed Atom response ({e})")
                continue

            if papers:
                logger.info(
                    "arXiv export API: %d papers via %r", len(papers), lucene[:100]
                )
                return papers
            # Reached arXiv, genuinely no match — relax the query instead of
            # retrying the same one against the other mirror.
            break

    if not reached:
        raise RuntimeError("; ".join(transport_errors) or "arXiv export API unreachable")

    logger.info("arXiv export API reachable but no matches for %r", query[:80])
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
    """Fallback via the arxiv package. Uses the same cleaned terms as the ladder."""
    terms = extract_search_terms(query)
    search_query = (
        " AND ".join(f'all:"{t}"' for t in terms) if terms else sanitize_search_query(query)
    )
    client = get_arxiv_client()
    search = arxiv.Search(
        query=search_query,
        max_results=max_results,
        sort_by=arxiv.SortCriterion.Relevance,
    )
    return [_paper_from_result(r) for r in client.results(search)]


def search_papers(query: str, max_results: int = 5) -> list[dict[str, Any]]:
    """Search arXiv. Returns [] when there are no matches; raises only on outage."""
    errors: list[str] = []
    export_reachable = False

    try:
        papers = _search_export_api(query, max_results)
        export_reachable = True
        if papers:
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

    if export_reachable:
        # arXiv answered every step of the ladder with an empty feed. That is a
        # legitimate "no results", not a tool failure.
        return []

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
    """Diagnostics for production — DNS + HTTP reachability + query building."""
    probe = "retrieval augmented generation"
    result: dict[str, Any] = {
        "dns_export_arxiv_org": None,
        "http_export_ok": False,
        "search_ok": False,
        "force_ipv4": _FORCE_IPV4,
        "probe_query": probe,
        "probe_terms": extract_search_terms(probe),
        "probe_ladder": build_query_ladder(probe),
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
        papers = search_papers(probe, max_results=1)
        result["search_ok"] = bool(papers)
        if papers:
            result["sample_title"] = papers[0].get("title")
        else:
            result["errors"].append("Search: reachable but returned no papers")
    except Exception as e:
        result["errors"].append(f"Search: {e}")

    return result
