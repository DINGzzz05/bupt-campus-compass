"""Test the real MCP initialize, discovery, validation and tool protocol."""

import os
import sys
from pathlib import Path

import pytest
from mcp import ClientSession, StdioServerParameters
from mcp.client.stdio import stdio_client
from sqlalchemy import create_engine, select
from sqlalchemy.orm import Session

from backend.app.core.config_manager import settings
from backend.app.db.database import Base
from backend.app.models.bupt import ActionTask
from backend.app.models.chat import ChatSession
from backend.app.models.user import User
from backend.app.services.bupt_actions import signed_draft


@pytest.mark.asyncio()
async def test_support_mcp_over_stdio(tmp_path):
    uri = f'sqlite:///{(tmp_path / "mcp.db").as_posix()}'
    engine = create_engine(uri)
    try:
        Base.metadata.create_all(engine)
        with Session(engine) as db, db.begin():
            db.add(User(id=7, username='mcp-test', email='protocol@example.com'))
            db.add(ChatSession(id=5, user_id=7, title='MCP protocol test'))
        project_root = Path(__file__).resolve().parents[3]
        params = StdioServerParameters(
            command=sys.executable,
            args=['-m', 'backend.app.services.bupt_actions'],
            cwd=str(project_root),
            env={
                **os.environ,
                'PYTHONPATH': str(project_root),
                'SQLALCHEMY_DATABASE_URI': uri,
                'SECRET_KEY': settings.SECRET_KEY.get_secret_value(),
            },
        )
        token = signed_draft(7, 5, 'Intermittent campus Wi-Fi access', None)
        async with stdio_client(params) as (reader, writer), ClientSession(reader, writer) as client:
            await client.initialize()
            tools = await client.list_tools()
            assert [tool.name for tool in tools.tools] == ['create_support_request']
            unconfirmed = await client.call_tool('create_support_request', {'confirmation': token, 'confirmed': False})
            assert unconfirmed.isError
            first = await client.call_tool('create_support_request', {'confirmation': token, 'confirmed': True})
            assert not first.isError
            second = await client.call_tool('create_support_request', {'confirmation': token, 'confirmed': True})
            assert first.content == second.content
        with Session(engine) as db:
            task = db.scalars(select(ActionTask)).one()
            assert task.status == 'queued'
            assert task.id == first.content[0].text
    finally:
        engine.dispose()
