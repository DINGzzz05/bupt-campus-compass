"""Durable records for the campus runtime."""

from datetime import datetime

from sqlalchemy import JSON, DateTime, ForeignKey, Integer, String, Text, UniqueConstraint, func
from sqlalchemy.orm import Mapped, mapped_column

from backend.app.db.database import Base


class ConversationRun(Base):
    __tablename__ = 'bupt_conversation_run'

    id: Mapped[str] = mapped_column(String(32), primary_key=True)
    session_id: Mapped[int] = mapped_column(ForeignKey('chat_session.id', ondelete='CASCADE'), index=True)
    request_id: Mapped[str] = mapped_column(String(128))
    domain: Mapped[str | None] = mapped_column(String(24))
    risk: Mapped[str | None] = mapped_column(String(24))
    status: Mapped[str] = mapped_column(String(24), default='running')
    artifacts: Mapped[list] = mapped_column(JSON, default=list)
    started_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())
    finished_at: Mapped[datetime | None] = mapped_column(DateTime)


class MemorySnapshot(Base):
    __tablename__ = 'bupt_memory_snapshot'
    __table_args__ = (UniqueConstraint('session_id', 'revision', 'through_message_id', name='uq_bupt_snapshot_version'),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    session_id: Mapped[int] = mapped_column(ForeignKey('chat_session.id', ondelete='CASCADE'), index=True)
    run_id: Mapped[str] = mapped_column(ForeignKey('bupt_conversation_run.id', ondelete='CASCADE'))
    through_message_id: Mapped[int] = mapped_column(Integer)
    revision: Mapped[int] = mapped_column(Integer)
    brief: Mapped[str] = mapped_column(Text)
    facts: Mapped[dict] = mapped_column(JSON)
    compressor: Mapped[str] = mapped_column(String(24))


class MemoryControl(Base):
    __tablename__ = 'bupt_memory_control'

    session_id: Mapped[int] = mapped_column(ForeignKey('chat_session.id', ondelete='CASCADE'), primary_key=True)
    cutoff: Mapped[int] = mapped_column(Integer, default=0)
    forgotten: Mapped[list] = mapped_column(JSON, default=list)
    corrections: Mapped[dict] = mapped_column(JSON, default=dict)
    revision: Mapped[int] = mapped_column(Integer, default=0)


class RetrievalRun(Base):
    __tablename__ = 'bupt_retrieval_run'

    run_id: Mapped[str] = mapped_column(ForeignKey('bupt_conversation_run.id', ondelete='CASCADE'), primary_key=True)
    details: Mapped[dict] = mapped_column(JSON)


class ModelAttempt(Base):
    __tablename__ = 'bupt_model_attempt'

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    run_id: Mapped[str] = mapped_column(ForeignKey('bupt_conversation_run.id', ondelete='CASCADE'), index=True)
    purpose: Mapped[str] = mapped_column(String(32))
    model: Mapped[str] = mapped_column(String(120))
    outcome: Mapped[str] = mapped_column(String(32))
    elapsed_ms: Mapped[int] = mapped_column(Integer)
    input_tokens: Mapped[int | None] = mapped_column(Integer)
    failure: Mapped[str | None] = mapped_column(String(80))


class ActionTask(Base):
    __tablename__ = 'bupt_action_task'
    __table_args__ = (UniqueConstraint('session_id', 'idempotency_key', name='uq_bupt_action_confirmation'),)

    id: Mapped[str] = mapped_column(String(32), primary_key=True)
    session_id: Mapped[int] = mapped_column(ForeignKey('chat_session.id', ondelete='CASCADE'), index=True)
    run_id: Mapped[str | None] = mapped_column(ForeignKey('bupt_conversation_run.id', ondelete='SET NULL'), index=True)
    idempotency_key: Mapped[str] = mapped_column(String(64))
    summary: Mapped[str] = mapped_column(Text)
    status: Mapped[str] = mapped_column(String(24), index=True)
    attempts: Mapped[int] = mapped_column(Integer, default=0)
    available_at: Mapped[datetime] = mapped_column(DateTime)
    lease_until: Mapped[datetime | None] = mapped_column(DateTime)
    lease_token: Mapped[str | None] = mapped_column(String(32))
    receipt: Mapped[str | None] = mapped_column(String(64))
    failure: Mapped[str | None] = mapped_column(String(80))
