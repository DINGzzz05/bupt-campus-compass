# ruff: noqa: RUF001
"""Compare full-history and compressed answer inputs across three recovery cases."""

import argparse
import asyncio
import json
from collections.abc import Callable
from pathlib import Path
from tempfile import TemporaryDirectory

import tiktoken
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from tokenizers import Tokenizer

from backend.app.core.config_manager import settings
from backend.app.db.database import Base
from backend.app.models.bupt import ConversationRun, MemoryControl
from backend.app.models.chat import ChatMessage, ChatSession
from backend.app.models.user import User
from backend.app.services import bupt_memory
from backend.app.services.bupt_model import ModelRouter
from backend.app.services.bupt_runtime import ANSWER_INSTRUCTION, answer_input

CASES = (
    ('academic_schedule', '沙河校区', '选课', '教务部学生服务页提供本科教务入口。'),
    ('research_access', '校外访问', '电子资源', '图书馆校外访问指南提供 WebVPN 使用方式。'),
    ('graduate_process', '就业去向', '毕业去向', '学生处指南列明申请人、学院和学校的审核顺序。'),
)


def _history(fact: str, topic: str, evidence: str) -> list[dict]:
    texts = (
        f'我需要了解{topic}，请记住当前业务背景是{fact}。',
        f'收到。在处理{topic}时，建议先核对官网上公开的材料、操作时间和入口，再决定下一步。',
        '我找过旧通知、收藏的页面和学校主页。网上有的流程没有标日期，我需要分辨当前页面和往年版本。',
        f'{evidence} 若页面涉及实际办事，建议按发布部门的通知操作。入口变更时可以从部门网站首页重新进入。',
        '我希望先找到可以核验的信息，保存资料出处，然后再看不同校区或年级是否适用。',
        '可以先记录部门名称、页面标题和复核日期，再查看当前业务对应的流程。如果确实没有公开信息，可以向相关部门咨询。',
        f'之后提到这件事时，还是指刚才说的{topic}。暂时只需要知道从哪找到官方说明。',
        '了解。接下来可以继续查看公开资料和官方入口。',
    )
    return [{'id': index, 'role': 'user' if index % 2 else 'assistant', 'text': text} for index, text in enumerate(texts, start=1)]


async def measure(count: Callable[[str], int], *, enable_ollama: bool) -> list[dict]:
    baseline = settings.BUPT_OLLAMA_ENABLED
    factory_before = bupt_memory.SessionLocal
    redis_before = settings.BUPT_REDIS_URL
    settings.BUPT_OLLAMA_ENABLED = enable_ollama
    settings.BUPT_REDIS_URL = None
    reports = []
    try:
        with TemporaryDirectory() as workdir:
            db_path = (Path(workdir) / 'memory.db').as_posix()
            engine = create_engine(f'sqlite:///{db_path}')
            try:
                Base.metadata.create_all(engine)
                factory = sessionmaker(bind=engine)
                bupt_memory.SessionLocal = factory
                for session_id, (name, fact, topic, evidence) in enumerate(CASES, start=1):
                    history = _history(fact, topic, evidence)
                    run_id = f'{session_id:032x}'
                    with factory.begin() as db:
                        db.add(User(id=session_id, username=name, email=f'{name}@example.com'))
                        db.add(ChatSession(id=session_id, user_id=session_id, title=name))
                        db.add(ConversationRun(id=run_id, session_id=session_id, request_id=run_id))
                        db.add(MemoryControl(session_id=session_id, corrections={'业务背景': fact}))
                        for message in history:
                            db.add(
                                ChatMessage(
                                    id=session_id * 100 + message['id'],
                                    session_id=session_id,
                                    content=message['text'],
                                    role=message['role'],
                                )
                            )
                    cutoff = session_id * 100 + len(history) + 1
                    context = bupt_memory.read(session_id, cutoff)
                    compressor = await bupt_memory.compress(context, ModelRouter())
                    snapshot_id = bupt_memory.save(session_id, run_id, context, compressor)
                    recovered = bupt_memory.read(session_id, cutoff)
                    question = '那我该从哪里查看官方说明？'
                    full_history = [{**message, 'id': session_id * 100 + message['id']} for message in history]
                    long_context = {'recent_messages': full_history, 'summary': '', 'confirmed_facts': context.facts}
                    before = count(answer_input(question, long_context, evidence))
                    after = count(answer_input(question, recovered.prompt(), evidence))
                    reports.append(
                        {
                            'case': name,
                            'full_tokens': before,
                            'compressed_tokens': after,
                            'compressor': compressor,
                            'restored': bool(
                                snapshot_id
                                and recovered.snapshot_id == snapshot_id
                                and recovered.brief == context.brief
                                and not recovered.delta
                                and recovered.facts['业务背景'] == fact
                                and len(recovered.recent) == bupt_memory.WINDOW_SIZE
                            ),
                        }
                    )
            finally:
                engine.dispose()
    finally:
        bupt_memory.SessionLocal = factory_before
        settings.BUPT_OLLAMA_ENABLED = baseline
        settings.BUPT_REDIS_URL = redis_before
    return reports


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--tokenizer', type=Path, help='Qwen2.5 tokenizer.json')
    parser.add_argument('--live-summary', action='store_true')
    args = parser.parse_args()
    if args.tokenizer:
        tokenizer = Tokenizer.from_file(str(args.tokenizer))
        count = lambda text: len(tokenizer.encode(template(text)).ids)
    else:
        encoder = tiktoken.get_encoding('cl100k_base')
        count = lambda text: len(encoder.encode(template(text), disallowed_special=()))
    cases = asyncio.run(measure(count, enable_ollama=args.live_summary))
    before = sum(case['full_tokens'] for case in cases)
    after = sum(case['compressed_tokens'] for case in cases)
    print(
        json.dumps(
            {
                'tokenizer': 'Qwen2.5 ChatML' if args.tokenizer else 'cl100k_base approximation',
                'input_reduction_percent': round((1 - after / before) * 100, 2),
                'restored': sum(case['restored'] for case in cases),
                'cases': cases,
            },
            indent=2,
        )
    )
    if not all(case['restored'] and (case['compressor'] == 'ollama' or not args.live_summary) for case in cases):
        raise SystemExit(1)


def template(text: str) -> str:
    return f'<|im_start|>system\n{ANSWER_INSTRUCTION}<|im_end|>\n<|im_start|>user\n{text}<|im_end|>\n<|im_start|>assistant\n'


if __name__ == '__main__':
    main()
