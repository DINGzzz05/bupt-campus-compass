# ruff: noqa: RUF001
"""Test browser credentials and DeepSeek SSE through the campus HTTP API."""

import json
from types import SimpleNamespace

import httpx
import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from backend.app.api import chat
from backend.app.core.config_manager import settings
from backend.app.core.security import get_current_user
from backend.app.db.database import Base, get_db
from backend.app.main import app
from backend.app.models.user import User
from backend.app.services import bupt_deepseek, bupt_memory, bupt_runtime

KEY = 'sk-demo-test-secret'
HEADERS = {'X-BUPT-DeepSeek-Key': KEY}


@pytest.fixture()
def campus_client(tmp_path, monkeypatch):
    engine = create_engine(f'sqlite:///{(tmp_path / "campus.db").as_posix()}')
    Base.metadata.create_all(engine)
    factory = sessionmaker(bind=engine)
    user = User(id=1, username='campus', email='campus@example.com')
    with factory.begin() as db:
        db.add(User(id=1, username=user.username, email=user.email))

    def db_override():
        with factory() as db:
            yield db

    monkeypatch.setitem(app.dependency_overrides, get_db, db_override)
    monkeypatch.setitem(app.dependency_overrides, get_current_user, lambda: user)
    monkeypatch.setattr(settings, 'BUPT_RAG_ENABLED', True)
    monkeypatch.setattr(settings, 'RAG_FORCE_MOCK', False)
    monkeypatch.setattr(settings, 'BUPT_OLLAMA_ENABLED', False)
    monkeypatch.setattr(settings, 'BUPT_REDIS_URL', None)
    monkeypatch.setattr(chat, 'get_rag_service', chat.RAGService)
    monkeypatch.setattr(bupt_runtime, 'SessionLocal', factory)
    monkeypatch.setattr(bupt_memory, 'SessionLocal', factory)
    with TestClient(app, raise_server_exceptions=True) as client:
        # The worker has no work in this fixture.
        yield client
    engine.dispose()


@pytest.mark.parametrize(
    ('upstream_status', 'terminal', 'generation'),
    [(200, True, 'deepseek'), (401, True, 'extractive_fallback'), (200, False, 'stream_interrupted')],
)
def test_deepseek_campus_turn(campus_client, monkeypatch, upstream_status, terminal, generation):
    calls = []

    def upstream(request: httpx.Request) -> httpx.Response:
        assert request.url.host == 'api.deepseek.com'
        assert request.headers['authorization'] == f'Bearer {KEY}'
        calls.append(request.url.path)
        if request.url.path == '/models':
            return httpx.Response(200, json={'data': [{'id': 'deepseek-flash'}]})
        if upstream_status != 200:
            return httpx.Response(upstream_status)
        body = json.loads(request.content)
        assert body['model'] == 'deepseek-flash'
        assert body['stream']
        events = [': keep-alive', 'data: {"choices":[{"delta":{"content":"请查看教务部学生服务页"}}]}']
        if terminal:
            events.extend(['data: {"choices":[{"finish_reason":"stop"}],"usage":{"prompt_tokens":42}}', 'data: [DONE]'])
        return httpx.Response(200, text='\n\n'.join(events) + '\n\n')

    transport = httpx.MockTransport(upstream)
    monkeypatch.setattr(
        bupt_deepseek,
        'httpx',
        SimpleNamespace(
            AsyncClient=lambda **kwargs: httpx.AsyncClient(transport=transport, **kwargs),
            Timeout=httpx.Timeout,
        ),
    )
    checked = campus_client.post('/api/bupt/deepseek/check', headers=HEADERS)
    assert checked.json() == {'status': 'ok', 'model': 'deepseek-flash'}
    response = campus_client.post('/api/chat/stream', json={'content': '北邮本科选课入口在哪里'}, headers=HEADERS)
    assert response.status_code == 200
    assert KEY not in response.text
    events = [json.loads(line[6:]) for line in response.text.splitlines() if line.startswith('data: ')]
    done = events[-1]
    assert done['type'] == 'done'
    assert done['bupt_trace']['generation'] == generation
    assert done['sources'][0]['kb_number'] == 'bupt-academic-system'
    trace = campus_client.get(f'/api/bupt/sessions/{done["session_id"]}/runs/{done["bupt_trace"]["run_id"]}')
    assert KEY not in trace.text
    attempts = trace.json()['model_attempts']
    assert len(attempts) == 1
    assert attempts[0]['model'] == 'deepseek-flash'
    if generation == 'deepseek':
        assert attempts[0]['input_tokens'] == 42
    else:
        assert done['stream_warning']
    local = campus_client.post('/api/chat/chat', json={'content': '本科怎么选课'}).json()
    assert local['assistant_message']['metadata']['bupt_trace']['generation'] == 'extractive'
    assert calls == ['/models', '/chat/completions']
