# ruff: noqa: RUF001
"""Read a revision-aware Redis window and persist immutable SQL summaries."""

import hashlib
import json
import logging
from dataclasses import dataclass
from functools import lru_cache

import httpx
import redis
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError

from backend.app.core.config_manager import settings
from backend.app.db.database import SessionLocal
from backend.app.models.bupt import MemoryControl, MemorySnapshot
from backend.app.models.chat import ChatMessage, ChatSession
from backend.app.services.bupt_model import ModelRouter

logger = logging.getLogger(__name__)
WINDOW_SIZE = 4


async def compress(context: 'Context', model: ModelRouter) -> str:
    older = '\n'.join(f'{entry["role"]}: {entry["text"]}' for entry in context.delta)
    try:
        summary = await model.text(
            'summary',
            '用中文将旧对话压缩为简明备忘，仅保留已说明的学业/校园诉求和未解决事项。不添加事实。',
            f'{context.brief}\n{older}',
        )
    except (httpx.HTTPError, ValueError, TypeError, AttributeError):
        summary = ''
    if summary.strip():
        context.brief = context.clean(summary.strip()[:600])
        return 'ollama'
    user_turns = '；'.join(entry['text'][:120] for entry in context.delta if entry['role'] == 'user')
    context.brief = '；'.join(filter(None, (context.brief, user_turns)))[-600:]
    return 'extractive'


@lru_cache(maxsize=4)
def _redis(url: str) -> redis.Redis:
    return redis.Redis.from_url(url, decode_responses=True, socket_connect_timeout=0.4, socket_timeout=0.4)


def _key(session_id: int) -> str:
    database = hashlib.sha256(settings.SQLALCHEMY_DATABASE_URI.encode()).hexdigest()[:12]
    return f'bupt:memory:{database}:{session_id}'


def invalidate(session_id: int) -> None:
    if settings.BUPT_REDIS_URL:
        try:
            _redis(settings.BUPT_REDIS_URL).delete(_key(session_id))
        except redis.RedisError:
            logger.warning('Campus memory cache invalidation unavailable')


@dataclass
class Context:
    recent: list[dict]
    delta: list[dict]
    brief: str
    facts: dict
    revision: int
    through: int
    snapshot_id: int | None
    forgotten: list[str]
    window_source: str

    def clean(self, text: str) -> str:
        for phrase in self.forgotten:
            text = text.replace(phrase, '[已撤回]')
        return text

    def prompt(self) -> dict:
        return {'summary': self.brief, 'confirmed_facts': self.facts, 'recent_messages': self.recent}


def read(session_id: int, message_id: int) -> Context:
    with SessionLocal() as db:
        control = db.get(MemoryControl, session_id)
        revision = control.revision if control else 0
        cutoff = control.cutoff if control else 0
        forgotten = list(control.forgotten) if control else []
        facts = dict(control.corrections) if control else {}
        history = select(ChatMessage).where(
            ChatMessage.session_id == session_id,
            ChatMessage.id < message_id,
            ChatMessage.id > cutoff,
        )
        newest = db.scalars(history.with_only_columns(ChatMessage.id).order_by(ChatMessage.id.desc()).limit(WINDOW_SIZE + 1)).all()
        window_ids = list(reversed(newest[:WINDOW_SIZE]))
        through = newest[-1] if len(newest) > WINDOW_SIZE else 0
        snapshot = db.scalar(
            select(MemorySnapshot)
            .where(
                MemorySnapshot.session_id == session_id,
                MemorySnapshot.through_message_id <= through,
                MemorySnapshot.revision == revision,
            )
            .order_by(MemorySnapshot.through_message_id.desc())
            .limit(1)
        )
        previous = snapshot.through_message_id if snapshot else cutoff
        older = db.scalars(history.where(ChatMessage.id > previous, ChatMessage.id <= through).order_by(ChatMessage.id.desc()).limit(28)).all()
        context = Context(
            [],
            [_message(row) for row in reversed(older)],
            snapshot.brief if snapshot else '',
            facts,
            revision,
            through,
            snapshot.id if snapshot else None,
            forgotten,
            'sql',
        )
        _window(db, session_id, window_ids, context)
    for message in context.delta:
        message['text'] = context.clean(message['text'])
    return context


def save(session_id: int, run_id: str, context: Context, compressor: str) -> int | None:
    with SessionLocal() as db:
        session = db.scalar(select(ChatSession.id).where(ChatSession.id == session_id).with_for_update())
        if session is None:
            return None
        control = db.get(MemoryControl, session_id)
        if (control.revision if control else 0) != context.revision:
            return None
        snapshot = MemorySnapshot(
            session_id=session_id,
            run_id=run_id,
            revision=context.revision,
            through_message_id=context.through,
            brief=context.brief,
            facts=context.facts,
            compressor=compressor,
        )
        db.add(snapshot)
        try:
            db.commit()
        except IntegrityError:
            db.rollback()
            return db.scalar(
                select(MemorySnapshot.id).where(
                    MemorySnapshot.session_id == session_id,
                    MemorySnapshot.revision == context.revision,
                    MemorySnapshot.through_message_id == context.through,
                )
            )
        return snapshot.id


def _message(row: ChatMessage) -> dict:
    return {'id': row.id, 'role': row.role, 'text': row.content[:800]}


def _window(db, session_id: int, window_ids: list[int], context: Context) -> None:
    cache = _redis(settings.BUPT_REDIS_URL) if settings.BUPT_REDIS_URL else None
    # The authenticated SQL message IDs and revision remain authoritative after a withdrawal.
    key = _key(session_id)
    version = [context.revision, window_ids]
    try:
        cached = json.loads(cache.get(key) or '{}') if cache else {}
        if cached.get('version') == version:
            context.recent = cached['messages']
            context.window_source = 'redis_hit'
            return
    except (redis.RedisError, ValueError, KeyError, TypeError, AttributeError):
        context.window_source = 'sql_fallback'
    for row in db.scalars(select(ChatMessage).where(ChatMessage.id.in_(window_ids)).order_by(ChatMessage.id)):
        message = _message(row)
        message['text'] = context.clean(message['text'])
        context.recent.append(message)
    if cache:
        try:
            cache.set(key, json.dumps({'version': version, 'messages': context.recent}), ex=900)
            context.window_source = 'redis_refresh'
        except redis.RedisError:
            context.window_source = 'sql_fallback'
