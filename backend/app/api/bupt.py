# ruff: noqa: RUF001
"""Authenticated campus memory, tracing, and confirmed support endpoints."""

from datetime import UTC
from typing import Annotated, Literal

import httpx
import jwt
from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field, SecretStr, StringConstraints
from sqlalchemy import delete, func, select, update
from sqlalchemy.orm import Session

from backend.app.core.bupt_credentials import deepseek_key
from backend.app.core.config_manager import settings
from backend.app.core.security import get_current_user
from backend.app.db.database import get_db
from backend.app.models.bupt import ActionTask, ConversationRun, MemoryControl, MemorySnapshot, ModelAttempt, RetrievalRun
from backend.app.models.chat import ChatMessage, ChatSession
from backend.app.models.user import User
from backend.app.services import bupt_actions, bupt_deepseek, bupt_memory

router = APIRouter(prefix='/api/bupt', tags=['bupt'])
Db = Annotated[Session, Depends(get_db)]
CurrentUser = Annotated[User, Depends(get_current_user)]
ShortText = Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=120)]


@router.post('/deepseek/check')
async def check_deepseek(_user: CurrentUser, credential: Annotated[SecretStr | None, Depends(deepseek_key)]) -> dict:
    if credential is None:
        raise HTTPException(422, '请填写 DeepSeek API Key')
    try:
        await bupt_deepseek.check_key(credential)
    except httpx.HTTPStatusError as exc:
        if exc.response.status_code in (401, 403):
            raise HTTPException(422, 'DeepSeek API Key 无效或无权访问') from None
        raise HTTPException(502, 'DeepSeek 暂时无法验证凭据') from None
    except httpx.HTTPError:
        raise HTTPException(502, '暂时无法连接 DeepSeek') from None
    return {'status': 'ok', 'model': bupt_deepseek.MODEL}


def _session(db: Session, user_id: int, session_id: int, *, lock=False) -> ChatSession:
    query = select(ChatSession).where(ChatSession.id == session_id, ChatSession.user_id == user_id)
    row = db.scalar(query.with_for_update() if lock else query) if settings.BUPT_RAG_ENABLED else None
    if row is None:
        raise HTTPException(404, '会话不存在')
    return row


class MemoryChange(BaseModel):
    operation: Literal['confirm', 'correct', 'forget', 'clear']
    key: ShortText | None = None
    value: ShortText | None = None


@router.get('/sessions/{session_id}/memory')
def memory_status(session_id: int, db: Db, user: CurrentUser) -> dict:
    _session(db, user.id, session_id)
    control = db.get(MemoryControl, session_id)
    return {'revision': control.revision if control else 0, 'facts': control.corrections if control else {}}


@router.post('/sessions/{session_id}/memory')
def change_memory(session_id: int, change: MemoryChange, db: Db, user: CurrentUser) -> dict:
    _session(db, user.id, session_id, lock=True)
    control = db.get(MemoryControl, session_id)
    if control is None:
        control = MemoryControl(session_id=session_id, revision=0, cutoff=0, forgotten=[], corrections={})
        db.add(control)
    facts = dict(control.corrections)
    forgotten = set(control.forgotten)
    if change.operation == 'clear':
        control.cutoff = db.scalar(select(func.max(ChatMessage.id)).where(ChatMessage.session_id == session_id)) or 0
        facts, forgotten = {}, set()
    elif change.operation == 'forget':
        if not change.key:
            raise HTTPException(422, '请输入要撤回的事实名称或短语')
        forgotten.add(change.key)
        previous = facts.pop(change.key, None)
        if previous:
            forgotten.add(previous)
    else:
        if not change.key or not change.value:
            raise HTTPException(422, '请填写事实名称和值')
        if change.operation == 'confirm' and change.key in facts and facts[change.key] != change.value:
            raise HTTPException(409, '该事实已确认，请用改写更新')
        if change.operation == 'correct' and change.key in facts and facts[change.key] != change.value:
            forgotten.add(facts[change.key])
        forgotten.discard(change.value)
        facts[change.key] = change.value
    if len(facts) > 20 or len(forgotten) > 80:
        raise HTTPException(422, '记忆管理条目已达到上限，请清空后重试')
    control.corrections = facts
    control.forgotten = sorted(forgotten)
    control.revision += 1
    revision = control.revision
    db.execute(delete(MemorySnapshot).where(MemorySnapshot.session_id == session_id))
    db.commit()
    bupt_memory.invalidate(session_id)
    return {'revision': revision, 'facts': facts}


@router.get('/sessions/{session_id}/runs/{run_id}')
def run_trace(session_id: int, run_id: str, db: Db, user: CurrentUser) -> dict:
    _session(db, user.id, session_id)
    run = db.get(ConversationRun, run_id)
    if run is None or run.session_id != session_id:
        raise HTTPException(404, '追踪记录不存在')
    retrieval = db.get(RetrievalRun, run.id)
    snapshots = db.scalars(select(MemorySnapshot.id).where(MemorySnapshot.run_id == run.id)).all()
    attempts = db.scalars(select(ModelAttempt).where(ModelAttempt.run_id == run.id).order_by(ModelAttempt.id)).all()
    actions = db.scalars(select(ActionTask).where(ActionTask.run_id == run.id)).all()
    return {
        'run_id': run.id,
        'request_id': run.request_id,
        'session_id': run.session_id,
        'status': run.status,
        'domain': run.domain,
        'risk': run.risk,
        'started_at': run.started_at.replace(tzinfo=UTC),
        'finished_at': run.finished_at.replace(tzinfo=UTC) if run.finished_at else None,
        'artifacts': run.artifacts,
        'retrieval': retrieval.details if retrieval else None,
        'memory_snapshot_ids': snapshots,
        'model_attempts': [
            {
                'purpose': item.purpose,
                'model': item.model,
                'outcome': item.outcome,
                'elapsed_ms': item.elapsed_ms,
                'input_tokens': item.input_tokens,
                'failure': item.failure,
            }
            for item in attempts
        ],
        'actions': [_task(task) for task in actions],
    }


class Draft(BaseModel):
    summary: str = Field(max_length=600)


class Confirmation(BaseModel):
    confirmation: str = Field(max_length=4500)
    confirmed: Literal[True]


@router.post('/sessions/{session_id}/support/draft')
def draft_support(session_id: int, draft: Draft, db: Db, user: CurrentUser) -> dict:
    _session(db, user.id, session_id)
    try:
        summary = bupt_actions.check_summary(draft.summary)
    except ValueError as exc:
        raise HTTPException(422, str(exc)) from exc
    metadata = db.scalar(
        select(ChatMessage.message_meta)
        .where(ChatMessage.session_id == session_id, ChatMessage.role == 'assistant')
        .order_by(ChatMessage.id.desc())
        .limit(1)
    )
    run_id = (metadata or {}).get('bupt_trace', {}).get('run_id')
    return {'summary': summary, 'confirmation': bupt_actions.signed_draft(user.id, session_id, summary, run_id)}


@router.post('/sessions/{session_id}/support/confirm', status_code=202)
async def confirm_support(session_id: int, confirmation: Confirmation, db: Db, user: CurrentUser) -> dict:
    _session(db, user.id, session_id)
    try:
        claims = bupt_actions.read_draft(confirmation.confirmation)
    except jwt.InvalidTokenError as exc:
        raise HTTPException(422, '确认已过期或无效，请重新预览') from exc
    if claims['sub'] != str(user.id) or claims['session_id'] != session_id:
        raise HTTPException(403, '确认与当前用户或会话不匹配')
    response = await bupt_actions.mcp.call_tool(
        'create_support_request',
        {'confirmation': confirmation.confirmation, 'confirmed': confirmation.confirmed},
    )
    return {'task_id': response[0].text}


def _task(task: ActionTask) -> dict:
    return {'task_id': task.id, 'status': task.status, 'attempts': task.attempts, 'receipt': task.receipt, 'failure': task.failure}


@router.get('/sessions/{session_id}/support')
def support_history(session_id: int, db: Db, user: CurrentUser) -> list[dict]:
    _session(db, user.id, session_id)
    return [
        _task(task)
        for task in db.scalars(select(ActionTask).where(ActionTask.session_id == session_id).order_by(ActionTask.available_at.desc()).limit(20))
    ]


@router.get('/sessions/{session_id}/support/{task_id}')
def support_status(session_id: int, task_id: str, db: Db, user: CurrentUser) -> dict:
    _session(db, user.id, session_id)
    task = db.get(ActionTask, task_id)
    if task is None or task.session_id != session_id:
        raise HTTPException(404, '任务不存在')
    return _task(task)


@router.post('/sessions/{session_id}/support/{task_id}/retry')
def retry_support(session_id: int, task_id: str, db: Db, user: CurrentUser) -> dict:
    _session(db, user.id, session_id)
    changed = db.execute(
        update(ActionTask)
        .where(
            ActionTask.id == task_id,
            ActionTask.session_id == session_id,
            ActionTask.status == 'needs_review',
        )
        .values(status='queued', attempts=0, failure=None, available_at=bupt_actions.now())
    )
    if not changed.rowcount:
        raise HTTPException(409, '仅待处理任务可以重试')
    db.commit()
    return {'task_id': task_id, 'status': 'queued'}
