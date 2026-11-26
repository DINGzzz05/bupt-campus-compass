# ruff: noqa: RUF001
"""Explicitly confirmed MCP support requests and a leased local worker."""

import asyncio
import logging
import re
from datetime import UTC, datetime, timedelta
from typing import Literal
from uuid import uuid4

import jwt
from mcp.server.fastmcp import FastMCP
from sqlalchemy import and_, or_, select, update
from sqlalchemy.exc import IntegrityError

from backend.app.core.config_manager import settings
from backend.app.db.database import SessionLocal
from backend.app.models.bupt import ActionTask, ConversationRun
from backend.app.models.chat import ChatSession

logger = logging.getLogger(__name__)
MAX_ATTEMPTS = 3
AUDIENCE = 'bupt:confirmed-support'
mcp = FastMCP('BUPT Campus Support')


def now() -> datetime:
    return datetime.now(UTC).replace(tzinfo=None)


def check_summary(summary: str) -> str:
    cleaned = ' '.join(summary.split())
    if not 8 <= len(cleaned) <= 600:
        raise ValueError('请填写 8 到 600 字的支持请求说明。')
    if re.search(r'\b[\w.+-]+@[\w.-]+\.[a-z]{2,}\b|\b\d{11,18}\b|(?:密码|验证码|token)\s*[:：=]', cleaned, re.IGNORECASE):
        raise ValueError('请先移除邮箱、长数字标识、密码或令牌。')
    return cleaned


def signed_draft(user_id: int, session_id: int, summary: str, run_id: str | None) -> str:
    return jwt.encode(
        {
            'sub': str(user_id),
            'aud': AUDIENCE,
            'exp': datetime.now(UTC) + timedelta(minutes=10),
            'jti': uuid4().hex,
            'session_id': session_id,
            'summary': summary,
            'run_id': run_id,
        },
        settings.SECRET_KEY.get_secret_value(),
        algorithm='HS256',
    )


def read_draft(confirmation: str) -> dict:
    return jwt.decode(
        confirmation,
        settings.SECRET_KEY.get_secret_value(),
        algorithms=['HS256'],
        audience=AUDIENCE,
        options={'require': ['sub', 'aud', 'exp', 'jti', 'session_id', 'summary']},
    )


def queue_confirmed(claims: dict) -> str:
    summary = check_summary(claims['summary'])
    with SessionLocal() as db:
        session = db.get(ChatSession, claims['session_id'])
        if not session or str(session.user_id) != claims['sub']:
            raise ValueError('会话不存在或无权访问。')
        existing = select(ActionTask.id).where(ActionTask.session_id == session.id, ActionTask.idempotency_key == claims['jti'])
        task_id = db.scalar(existing)
        if task_id:
            return task_id
        run = db.get(ConversationRun, claims['run_id']) if claims.get('run_id') else None
        task = ActionTask(
            id=uuid4().hex,
            session_id=session.id,
            run_id=run.id if run and run.session_id == session.id else None,
            summary=summary,
            idempotency_key=claims['jti'],
            status='queued',
            available_at=now(),
        )
        db.add(task)
        try:
            db.commit()
        except IntegrityError:
            db.rollback()
            if existing_id := db.scalar(existing):
                return existing_id
            raise
        return task.id


@mcp.tool(structured_output=False)
async def create_support_request(confirmation: str, confirmed: Literal[True]) -> str:
    """Queue the support request identified by the user's signed confirmation."""
    if confirmed is not True:
        raise ValueError('Explicit confirmation is required')
    return await asyncio.to_thread(queue_confirmed, read_draft(confirmation))


def _eligible(at: datetime):
    return or_(
        and_(ActionTask.status == 'queued', ActionTask.available_at <= at),
        and_(ActionTask.status == 'running', ActionTask.lease_until <= at),
    )


def claim() -> tuple[str, str, int] | None:
    at = now()
    with SessionLocal.begin() as db:
        candidate = db.execute(
            select(ActionTask.id, ActionTask.attempts).where(_eligible(at)).order_by(ActionTask.available_at, ActionTask.id).limit(1)
        ).first()
        if not candidate:
            return None
        task_id, attempts = candidate
        where = (ActionTask.id == task_id, ActionTask.attempts == attempts, _eligible(at))
        if attempts >= MAX_ATTEMPTS:
            db.execute(update(ActionTask).where(*where).values(status='needs_review', lease_token=None, lease_until=None, failure='lease_exhausted'))
            return None
        token = uuid4().hex
        changed = db.execute(
            update(ActionTask)
            .where(*where)
            .values(
                status='running',
                attempts=attempts + 1,
                lease_token=token,
                lease_until=at + timedelta(seconds=20),
            )
        )
        return (task_id, token, attempts + 1) if changed.rowcount else None


def _deliver(task_id: str) -> str:
    # This is a durable local intake receipt. No external recipient is called.
    return f'BUPT-{task_id}'


def finish(task_id: str, token: str, attempt: int, *, receipt=None, failure=None) -> None:
    at = now()
    state = 'completed' if receipt else 'needs_review' if attempt >= MAX_ATTEMPTS else 'queued'
    with SessionLocal.begin() as db:
        db.execute(
            update(ActionTask)
            .where(ActionTask.id == task_id, ActionTask.status == 'running', ActionTask.lease_token == token, ActionTask.lease_until > at)
            .values(
                status=state,
                receipt=receipt,
                failure=failure,
                lease_token=None,
                lease_until=None,
                available_at=at + timedelta(seconds=2**attempt) if state == 'queued' else at,
            )
        )


async def worker() -> None:
    while True:
        try:
            leased = await asyncio.to_thread(claim)
            if leased:
                task_id, token, attempt = leased
                try:
                    receipt = await asyncio.wait_for(asyncio.to_thread(_deliver, task_id), timeout=8)
                except Exception as exc:
                    await asyncio.to_thread(finish, task_id, token, attempt, failure=type(exc).__name__)
                else:
                    await asyncio.to_thread(finish, task_id, token, attempt, receipt=receipt)
        except Exception:
            logger.exception('Campus action worker encountered a storage error')
        await asyncio.sleep(0.5)


if __name__ == '__main__':
    mcp.run(transport='stdio')
