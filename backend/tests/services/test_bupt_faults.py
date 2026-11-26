# ruff: noqa: RUF001
"""Deterministic fault fixtures covering the campus runtime and action worker."""

from datetime import timedelta

import httpx
import pytest
from langchain_core.documents import Document
from redis import ConnectionError as RedisConnectionError
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from backend.app.core.config_manager import settings
from backend.app.db.database import Base
from backend.app.models.bupt import ActionTask, ConversationRun
from backend.app.models.chat import ChatMessage, ChatSession
from backend.app.models.user import User
from backend.app.services import bupt_actions, bupt_knowledge, bupt_memory, bupt_model, bupt_runtime


@pytest.fixture()
def storage(tmp_path, monkeypatch):
    engine = create_engine(f'sqlite:///{tmp_path / "runtime.db"}')
    Base.metadata.create_all(engine)
    factory = sessionmaker(bind=engine)
    for module in (bupt_actions, bupt_memory, bupt_runtime):
        monkeypatch.setattr(module, 'SessionLocal', factory)
    with factory.begin() as db:
        db.add(User(id=1, username='campus-test', email='test@example.com'))
        db.add(ChatSession(id=1, user_id=1, title='Campus'))
        db.add_all(
            [
                ChatMessage(id=1, session_id=1, role='user', content='我想了解教务系统'),
                ChatMessage(id=2, session_id=1, role='user', content='选课入口在哪里'),
            ]
        )
    yield factory
    engine.dispose()


@pytest.fixture()
def _ollama(monkeypatch):
    monkeypatch.setattr(settings, 'BUPT_OLLAMA_ENABLED', True)
    monkeypatch.setattr(settings, 'BUPT_REDIS_URL', None)
    monkeypatch.setattr(bupt_model, '_BREAKERS', {key: bupt_model.CircuitBreaker() for key in bupt_model._BREAKERS})
    doc = Document(
        page_content='本科教务系统入口在教务部学生服务页。',
        metadata={
            'kb_url': 'https://jwbs.bupt.edu.cn/xsfw.htm',
            'kb_number': 'test',
            'status': 'ACTIVE',
            'short_description': '教务系统',
        },
    )
    monkeypatch.setattr(bupt_knowledge, 'search', lambda *_args, **_kwargs: ([doc], {'retrieval': 'stub'}))


@pytest.mark.parametrize(
    ('failure', 'expected'),
    [
        ('timeout_before_token', 'extractive_fallback'),
        ('invalid_ndjson', 'extractive_fallback'),
        ('timeout_after_token', 'stream_interrupted'),
        ('eof_after_token', 'stream_interrupted'),
    ],
)
@pytest.mark.asyncio()
@pytest.mark.usefixtures('_ollama')
async def test_model_stream_failures(storage, monkeypatch, failure, expected):
    async def model_events(_self, purpose, _instruction, _data):
        if purpose in ('route', 'risk'):
            yield {'message': {'content': 'academic' if purpose == 'route' else 'allow'}, 'done': True}
            return
        if failure == 'invalid_ndjson':
            raise ValueError('invalid JSON')
        if failure.endswith('after_token'):
            yield {'message': {'content': '已经收到的前缀'}}
        if failure.startswith('timeout'):
            raise httpx.ReadTimeout('injected timeout')

    monkeypatch.setattr(bupt_model.ModelRouter, '_events', model_events)
    harness = bupt_runtime.RuntimeHarness(1, 2, '选课入口在哪里')
    result = await harness.result()
    assert result['metadata']['bupt_trace']['generation'] == expected
    with storage() as db:
        assert db.get(ConversationRun, harness.id).status == ('interrupted' if result['interrupted'] else 'completed')
    if failure.endswith('after_token'):
        assert result['message'] == '已经收到的前缀'
        assert result['metadata']['stream_warning']
    else:
        assert '教务部学生服务页' in result['message']


def test_circuit_allows_only_one_half_open_probe(monkeypatch):
    current = [0.0]
    monkeypatch.setattr(bupt_model, 'monotonic', lambda: current[0])
    breaker = bupt_model.CircuitBreaker(threshold=1, cooldown=5)
    permit = breaker.acquire()
    assert permit
    stale = breaker.acquire()
    breaker.finish(permit, False)
    assert not breaker.acquire()
    current[0] += 6
    probe = breaker.acquire()
    assert probe
    assert stale
    assert not breaker.acquire()
    breaker.finish(stale, True)
    assert not breaker.acquire()
    breaker.finish(probe, True)
    assert breaker.opened is None
    assert breaker.acquire()


def test_redis_disconnect_retains_sql_window(storage, monkeypatch):
    class OfflineRedis:
        def get(self, _key):
            raise RedisConnectionError('injected cache outage')

        def set(self, *_args, **_kwargs):
            raise RedisConnectionError('injected cache outage')

    monkeypatch.setattr(settings, 'BUPT_REDIS_URL', 'redis://localhost:65530')
    monkeypatch.setattr(bupt_memory, '_redis', lambda _url: OfflineRedis())
    result = bupt_memory.read(1, 2)
    assert result.window_source == 'sql_fallback'
    assert result.recent[0]['text'] == '我想了解教务系统'


def test_embedding_disconnect_keeps_lexical_candidates(monkeypatch):
    def outage(*_args):
        raise httpx.ConnectError('injected embedding outage')

    monkeypatch.setattr(settings, 'BUPT_OLLAMA_ENABLED', True)
    monkeypatch.setattr(bupt_knowledge, '_collection', outage)
    documents, trace = bupt_knowledge.search('北邮本科选课入口')
    assert trace['retrieval'] == 'bm25_fallback'
    assert documents[0].metadata['kb_number'] == 'bupt-academic-system'


def _task():
    claims = bupt_actions.read_draft(bupt_actions.signed_draft(1, 1, '校园网络访问有问题需要协助', None))
    task_id = bupt_actions.queue_confirmed(claims)
    assert bupt_actions.queue_confirmed(claims) == task_id
    return task_id


def test_stale_worker_cannot_acknowledge_recovered_lease(storage, monkeypatch):
    task_id = _task()
    old = bupt_actions.claim()
    assert old is not None
    now = bupt_actions.now()
    monkeypatch.setattr(bupt_actions, 'now', lambda: now + timedelta(seconds=25))
    recovered = bupt_actions.claim()
    assert recovered is not None
    assert recovered[1] != old[1]
    bupt_actions.finish(*old, receipt='stale')
    bupt_actions.finish(*recovered, receipt='current')
    with storage() as db:
        assert db.get(ActionTask, task_id).receipt == 'current'


def test_repeated_worker_failures_require_review(storage, monkeypatch):
    task_id = _task()
    current = [bupt_actions.now() + timedelta(seconds=1)]
    monkeypatch.setattr(bupt_actions, 'now', lambda: current[0])
    for _ in range(bupt_actions.MAX_ATTEMPTS):
        leased = bupt_actions.claim()
        assert leased is not None
        bupt_actions.finish(*leased, failure='TimeoutError')
        current[0] += timedelta(seconds=20)
    assert bupt_actions.claim() is None
    with storage() as db:
        record = db.get(ActionTask, task_id)
        assert record.status == 'needs_review'
        assert record.failure == 'TimeoutError'
