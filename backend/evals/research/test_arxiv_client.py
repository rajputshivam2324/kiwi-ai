"""Tests for arXiv client resilience."""

from unittest.mock import patch

import pytest

from app.services.research.arxiv_client import (
    _parse_export_atom,
    _search_export_api,
    build_query_ladder,
    extract_search_terms,
    fetch_papers_by_ids,
    search_papers,
)
from app.services.research.tools import ResearchTools

SAMPLE_ATOM = """<?xml version="1.0" encoding="UTF-8"?>
<feed xmlns="http://www.w3.org/2005/Atom"
      xmlns:arxiv="http://arxiv.org/schemas/atom">
  <entry>
    <id>http://arxiv.org/abs/2203.08975v2</id>
    <title> A Survey of Multi-Agent Deep Reinforcement Learning with Communication </title>
    <summary>Communication is effective for coordinating agents.</summary>
    <published>2022-03-16T00:00:00Z</published>
    <author><name>Changxi Zhu</name></author>
    <category term="cs.MA"/>
  </entry>
</feed>"""


def test_parse_export_atom():
    papers = _parse_export_atom(SAMPLE_ATOM)
    assert len(papers) == 1
    assert papers[0]["arxiv_id"] == "2203.08975v2"
    assert "Survey" in papers[0]["title"]
    assert papers[0]["url"] == "https://arxiv.org/abs/2203.08975v2"


def test_search_papers_uses_client_fallback_when_export_fails():
    with patch(
        "app.services.research.arxiv_client._search_export_api",
        side_effect=RuntimeError("blocked"),
    ):
        with patch(
            "app.services.research.arxiv_client._search_client_api",
            return_value=[
                {
                    "arxiv_id": "1234.56789",
                    "title": "Fallback Paper",
                    "authors": ["A. Author"],
                    "abstract": "Test abstract",
                    "url": "https://arxiv.org/abs/1234.56789",
                    "pdf_url": "https://arxiv.org/pdf/1234.56789.pdf",
                    "published": "2024-01-01",
                    "categories": ["cs.AI"],
                }
            ],
        ):
            papers = search_papers("multi-agent", max_results=1)
            assert papers[0]["title"] == "Fallback Paper"


@pytest.mark.integration
def test_search_papers_live():
    papers = search_papers("multi-agent coordination", max_results=2)
    assert len(papers) >= 1
    assert papers[0]["arxiv_id"]
    assert papers[0]["url"].startswith("https://arxiv.org/abs/")


@pytest.mark.integration
def test_fetch_papers_by_ids_live():
    papers = fetch_papers_by_ids(["1706.03762"])
    assert len(papers) == 1
    assert "Attention" in papers[0]["title"]


# --- Query building -----------------------------------------------------------
# Joining every word of a natural-language question with AND makes filler words
# ("what", "are", "the", "papers", "about") mandatory search terms, which
# returned zero results for essentially every real user query.


def test_extract_search_terms_drops_conversational_filler():
    terms = extract_search_terms(
        "what are the latest papers about mixture of experts routing"
    )
    assert terms == ["mixture", "experts", "routing"]


def test_extract_search_terms_keeps_topic_when_query_is_long():
    # The topic must survive truncation — it used to be cut off by filler words
    # consuming the term budget.
    terms = extract_search_terms(
        "could you please show me some recent papers about "
        "graph neural networks for drug discovery"
    )
    assert "graph" in terms
    assert "discovery" in terms


def test_extract_search_terms_deduplicates_and_lowercases():
    assert extract_search_terms("Transformers transformers TRANSFORMERS") == [
        "transformers"
    ]


def test_build_query_ladder_relaxes_from_phrase_to_and_to_or():
    ladder = build_query_ladder("papers on retrieval augmented generation evaluation")
    assert ladder[0] == 'all:"retrieval augmented generation evaluation"'
    assert ladder[1] == (
        'all:"retrieval" AND all:"augmented" AND all:"generation" AND all:"evaluation"'
    )
    assert ladder[2].count(" OR ") == 3
    assert all("all:" in step for step in ladder)


def test_build_query_ladder_single_term():
    assert build_query_ladder("explain attention") == ['all:"attention"']


def test_build_query_ladder_empty_when_no_content_terms():
    assert build_query_ladder("what are the latest papers?") == []


# --- No-results is not an error ----------------------------------------------


def test_search_papers_returns_empty_when_arxiv_has_no_matches():
    """A reachable arXiv with an empty feed must not raise.

    Raising here is what surfaced to users as "the search tool encountered an
    error" instead of "no papers matched".
    """
    empty_feed = '<?xml version="1.0"?><feed xmlns="http://www.w3.org/2005/Atom"/>'
    with patch(
        "app.services.research.arxiv_client._http_get_export", return_value=empty_feed
    ):
        with patch(
            "app.services.research.arxiv_client._search_client_api", return_value=[]
        ):
            assert search_papers("some obscure topic with no hits") == []


def test_search_papers_raises_when_arxiv_unreachable():
    with patch(
        "app.services.research.arxiv_client._http_get_export",
        side_effect=OSError("network unreachable"),
    ):
        with patch(
            "app.services.research.arxiv_client._search_client_api",
            side_effect=RuntimeError("also down"),
        ):
            with pytest.raises(RuntimeError):
                search_papers("multi-agent coordination")


def test_export_search_walks_ladder_until_a_step_matches():
    calls: list[str] = []

    def fake_get(url: str) -> str:
        calls.append(url)
        # First ladder step (the exact phrase) matches nothing.
        if "%20AND%20" not in url:
            return '<?xml version="1.0"?><feed xmlns="http://www.w3.org/2005/Atom"/>'
        return SAMPLE_ATOM

    with patch(
        "app.services.research.arxiv_client._http_get_export", side_effect=fake_get
    ):
        papers = _search_export_api("papers on multi agent communication", 5)

    assert len(papers) == 1
    assert len(calls) == 2, "should stop at the first ladder step that matches"


def test_search_arxiv_live_reports_no_matches_as_success():
    """The tool layer must not report an empty result as a failure."""
    with patch(
        "app.services.research.tools.search_papers", return_value=[]
    ):
        result = ResearchTools.search_arxiv_live("obscure topic", max_results=5)

    assert result["success"] is True
    assert result["results_count"] == 0
    assert "not an error" in result["note"]
