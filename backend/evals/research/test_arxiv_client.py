"""Tests for arXiv client resilience."""

from unittest.mock import patch

import pytest

from app.services.research.arxiv_client import (
    _parse_export_atom,
    fetch_papers_by_ids,
    search_papers,
)

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


def test_search_papers_uses_export_fallback_when_client_fails():
    with patch(
        "app.services.research.arxiv_client.get_arxiv_client",
        side_effect=RuntimeError("blocked"),
    ):
        with patch(
            "app.services.research.arxiv_client._search_export_api",
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
