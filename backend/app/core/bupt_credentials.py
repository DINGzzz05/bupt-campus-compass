"""Validate browser-supplied DeepSeek credentials without echoing them."""

import re
from typing import Annotated

from fastapi import Header, HTTPException
from pydantic import SecretStr

from backend.app.core.config_manager import settings


def deepseek_key(value: Annotated[str | None, Header(alias='X-BUPT-DeepSeek-Key')] = None) -> SecretStr | None:
    if value is None:
        return None
    if not settings.BUPT_RAG_ENABLED or settings.RAG_FORCE_MOCK:
        raise HTTPException(404, '北邮知识问答模式未开启')
    if not re.fullmatch(r'[!-~]{8,256}', value):
        raise HTTPException(422, 'DeepSeek API Key 格式无效')
    return SecretStr(value)
