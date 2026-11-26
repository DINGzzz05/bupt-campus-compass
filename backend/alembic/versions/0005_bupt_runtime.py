"""Persist BUPT conversation traces, memory snapshots and support tasks."""

import sqlalchemy as sa
from alembic import op

revision = '0005'
down_revision = '0004'
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        'bupt_conversation_run',
        sa.Column('id', sa.String(length=32), nullable=False),
        sa.Column('session_id', sa.Integer(), nullable=False),
        sa.Column('request_id', sa.String(length=128), nullable=False),
        sa.Column('domain', sa.String(length=24), nullable=True),
        sa.Column('risk', sa.String(length=24), nullable=True),
        sa.Column('status', sa.String(length=24), nullable=False),
        sa.Column('artifacts', sa.JSON(), nullable=False),
        sa.Column('started_at', sa.DateTime(), server_default=sa.text('now()'), nullable=False),
        sa.Column('finished_at', sa.DateTime(), nullable=True),
        sa.ForeignKeyConstraint(['session_id'], ['chat_session.id'], ondelete='CASCADE'),
        sa.PrimaryKeyConstraint('id'),
    )
    op.create_index(op.f('ix_bupt_conversation_run_session_id'), 'bupt_conversation_run', ['session_id'], unique=False)
    op.create_table(
        'bupt_memory_control',
        sa.Column('session_id', sa.Integer(), nullable=False),
        sa.Column('cutoff', sa.Integer(), nullable=False),
        sa.Column('forgotten', sa.JSON(), nullable=False),
        sa.Column('corrections', sa.JSON(), nullable=False),
        sa.Column('revision', sa.Integer(), nullable=False),
        sa.ForeignKeyConstraint(['session_id'], ['chat_session.id'], ondelete='CASCADE'),
        sa.PrimaryKeyConstraint('session_id'),
    )
    op.create_table(
        'bupt_action_task',
        sa.Column('id', sa.String(length=32), nullable=False),
        sa.Column('session_id', sa.Integer(), nullable=False),
        sa.Column('run_id', sa.String(length=32), nullable=True),
        sa.Column('idempotency_key', sa.String(length=64), nullable=False),
        sa.Column('summary', sa.Text(), nullable=False),
        sa.Column('status', sa.String(length=24), nullable=False),
        sa.Column('attempts', sa.Integer(), nullable=False),
        sa.Column('available_at', sa.DateTime(), nullable=False),
        sa.Column('lease_until', sa.DateTime(), nullable=True),
        sa.Column('lease_token', sa.String(length=32), nullable=True),
        sa.Column('receipt', sa.String(length=64), nullable=True),
        sa.Column('failure', sa.String(length=80), nullable=True),
        sa.ForeignKeyConstraint(['run_id'], ['bupt_conversation_run.id'], ondelete='SET NULL'),
        sa.ForeignKeyConstraint(['session_id'], ['chat_session.id'], ondelete='CASCADE'),
        sa.PrimaryKeyConstraint('id'),
        sa.UniqueConstraint('session_id', 'idempotency_key', name='uq_bupt_action_confirmation'),
    )
    op.create_index(op.f('ix_bupt_action_task_run_id'), 'bupt_action_task', ['run_id'], unique=False)
    op.create_index(op.f('ix_bupt_action_task_session_id'), 'bupt_action_task', ['session_id'], unique=False)
    op.create_index(op.f('ix_bupt_action_task_status'), 'bupt_action_task', ['status'], unique=False)
    op.create_table(
        'bupt_memory_snapshot',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('session_id', sa.Integer(), nullable=False),
        sa.Column('run_id', sa.String(length=32), nullable=False),
        sa.Column('through_message_id', sa.Integer(), nullable=False),
        sa.Column('revision', sa.Integer(), nullable=False),
        sa.Column('brief', sa.Text(), nullable=False),
        sa.Column('facts', sa.JSON(), nullable=False),
        sa.Column('compressor', sa.String(length=24), nullable=False),
        sa.ForeignKeyConstraint(['run_id'], ['bupt_conversation_run.id'], ondelete='CASCADE'),
        sa.ForeignKeyConstraint(['session_id'], ['chat_session.id'], ondelete='CASCADE'),
        sa.PrimaryKeyConstraint('id'),
        sa.UniqueConstraint('session_id', 'revision', 'through_message_id', name='uq_bupt_snapshot_version'),
    )
    op.create_index(op.f('ix_bupt_memory_snapshot_session_id'), 'bupt_memory_snapshot', ['session_id'], unique=False)
    op.create_table(
        'bupt_model_attempt',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('run_id', sa.String(length=32), nullable=False),
        sa.Column('purpose', sa.String(length=32), nullable=False),
        sa.Column('model', sa.String(length=120), nullable=False),
        sa.Column('outcome', sa.String(length=32), nullable=False),
        sa.Column('elapsed_ms', sa.Integer(), nullable=False),
        sa.Column('input_tokens', sa.Integer(), nullable=True),
        sa.Column('failure', sa.String(length=80), nullable=True),
        sa.ForeignKeyConstraint(['run_id'], ['bupt_conversation_run.id'], ondelete='CASCADE'),
        sa.PrimaryKeyConstraint('id'),
    )
    op.create_index(op.f('ix_bupt_model_attempt_run_id'), 'bupt_model_attempt', ['run_id'], unique=False)
    op.create_table(
        'bupt_retrieval_run',
        sa.Column('run_id', sa.String(length=32), nullable=False),
        sa.Column('details', sa.JSON(), nullable=False),
        sa.ForeignKeyConstraint(['run_id'], ['bupt_conversation_run.id'], ondelete='CASCADE'),
        sa.PrimaryKeyConstraint('run_id'),
    )


def downgrade() -> None:
    op.drop_table('bupt_retrieval_run')
    op.drop_table('bupt_model_attempt')
    op.drop_table('bupt_memory_snapshot')
    op.drop_table('bupt_action_task')
    op.drop_table('bupt_memory_control')
    op.drop_table('bupt_conversation_run')
