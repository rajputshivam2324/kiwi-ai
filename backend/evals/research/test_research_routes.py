"""SSE and ingestion regressions through the actual FastAPI router."""
import json

from fastapi import FastAPI
from fastapi.testclient import TestClient
import pytest

from app.deps.rate_limit import rate_limit_dependency
from app.routers import research


@pytest.fixture
def client():
    application = FastAPI()
    application.include_router(research.router)
    application.dependency_overrides[rate_limit_dependency] = lambda: None
    class Agent:
        def query_stream(self, **kwargs):
            yield {"type": "sources", "data": []}
            yield {"type": "content", "data": "Evidence-based answer"}
    application.dependency_overrides[research.get_rag_agent] = lambda: Agent()
    application.dependency_overrides[research.get_vectorstore_service] = lambda: object()
    with TestClient(application) as connection:
        yield connection


def test_stream_endpoint_emits_tokens_and_completion(client):
    response = client.post("/chat/stream", json={"message": "explain attention"})
    assert response.status_code == 200
    assert response.headers["content-type"].startswith("text/event-stream")
    events = [json.loads(line[6:]) for line in response.text.splitlines() if line.startswith("data: ") and line != "data: [DONE]"]
    assert any(e.get("data") == "Evidence-based answer" for e in events)
    assert response.text.endswith("data: [DONE]\n\n")


def test_ingest_exposes_partial_failure_details(client, monkeypatch):
    def ingest(**kwargs):
        assert kwargs["include_full_text"] is False
        return {"status": "partial", "documents_added": 4, "arxiv_ids": ["a"], "skipped_arxiv_ids": [],
                "errors": [{"arxiv_id": "b", "error": "unreadable PDF"}]}
    monkeypatch.setattr("app.scripts.ingest_arxiv.ingest_papers", ingest)
    response = client.post("/ingest", json={"query": "attention", "include_full_text": False})
    assert response.status_code == 200
    assert response.json()["status"] == "partial" and response.json()["errors"][0]["arxiv_id"] == "b"
    assert client.post("/ingest", json={"query": "attention", "max_results": -1}).status_code == 422
