"""Owned memory, SSE, and ingestion through the actual FastAPI router."""
import json
import os
import uuid
from fastapi import FastAPI
from fastapi.testclient import TestClient
import pytest

from app.deps.rate_limit import rate_limit_dependency
from app.deps.auth import require_auth
from app.routers import research
from app.services.memory import ConversationMemory


@pytest.fixture
def client():
    if not os.getenv('TEST_DATABASE_URL'):
        pytest.skip('TEST_DATABASE_URL required')
    application = FastAPI()
    application.include_router(research.router)
    application.dependency_overrides[rate_limit_dependency] = lambda: None
    user = 'route-test-' + uuid.uuid4().hex
    application.dependency_overrides[require_auth] = lambda: user
    class Agent:
        def query_stream(self, **kwargs):
            yield {'type':'sources','data':[]}
            yield {'type':'content','data':'Evidence-based answer'}
        def query(self, **kwargs):
            return {'answer':'Evidence-based answer','sources':[]}
    memory = ConversationMemory()
    application.dependency_overrides[research.get_rag_agent] = lambda: Agent()
    application.dependency_overrides[research.get_vectorstore_service] = lambda: object()
    application.dependency_overrides[research.get_memory] = lambda: memory
    with TestClient(application) as connection:
        yield connection
    for conversation in memory.list(user):
        memory.delete(conversation['id'], user)


def test_stream_endpoint_emits_tokens_and_persists_completed_turn(client):
    response = client.post('/chat/stream', json={'message':'explain attention'})
    assert response.status_code == 200
    assert response.headers['content-type'].startswith('text/event-stream')
    events = [json.loads(line[6:]) for line in response.text.splitlines() if line.startswith('data: ') and line != 'data: [DONE]']
    assert any(e.get('data') == 'Evidence-based answer' for e in events)
    assert response.text.endswith('data: [DONE]\n\n')
    conv_id = next(e['data'] for e in events if e['type'] == 'conversation_id')
    messages = client.get(f'/conversations/{conv_id}/messages').json()['messages']
    assert [m['role'] for m in messages] == ['user','assistant']


def test_research_rejects_body_identity_and_other_users_conversation(client):
    assert client.post('/chat', json={'message':'hi','user_id':'someone-else'}).status_code == 403
    assert client.get('/conversations?user_id=someone-else').status_code == 403
    assert client.get(f'/conversations/{uuid.uuid4()}/messages').status_code == 404
    assert client.post('/chat', json={'message':'hi','conversation_id':str(uuid.uuid4())}).status_code == 404


def test_ingest_exposes_partial_failure_details(client, monkeypatch):
    def ingest(**kwargs):
        assert kwargs['include_full_text'] is False
        return {'status':'partial','documents_added':4,'arxiv_ids':['a'],'skipped_arxiv_ids':[],
                'errors':[{'arxiv_id':'b','error':'unreadable PDF'}]}
    monkeypatch.setattr('app.scripts.ingest_arxiv.ingest_papers', ingest)
    response = client.post('/ingest', json={'query':'attention','include_full_text':False})
    assert response.status_code == 200 and response.json()['status'] == 'partial'
    assert client.post('/ingest', json={'query':'attention','max_results':-1}).status_code == 422
