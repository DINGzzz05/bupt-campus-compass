"""DeepSeek transport for credentials supplied with a single campus request."""

import json
from collections.abc import AsyncIterator

import httpx
from pydantic import SecretStr

BASE_URL = 'https://api.deepseek.com'
MODEL = 'deepseek-flash'


def _headers(key: SecretStr) -> dict[str, str]:
    return {'Authorization': f'Bearer {key.get_secret_value()}'}


async def check_key(key: SecretStr) -> None:
    async with httpx.AsyncClient(timeout=8, follow_redirects=False) as client:
        response = await client.get(f'{BASE_URL}/models', headers=_headers(key))
        response.raise_for_status()


async def chat_events(key: SecretStr, instruction: str, data: str) -> AsyncIterator[dict]:
    """Normalize provider SSE to ModelRouter's token and terminal event shape."""
    finish_reason = None
    input_tokens = None
    async with (
        httpx.AsyncClient(timeout=httpx.Timeout(35, connect=5), follow_redirects=False) as client,
        client.stream(
            'POST',
            f'{BASE_URL}/chat/completions',
            headers=_headers(key),
            json={
                'model': MODEL,
                'messages': [{'role': 'system', 'content': instruction}, {'role': 'user', 'content': data}],
                'thinking': {'type': 'disabled'},
                'max_tokens': 350,
                'stream': True,
                'stream_options': {'include_usage': True},
            },
        ) as response,
    ):
        response.raise_for_status()
        async for line in response.aiter_lines():
            if not line.startswith('data:'):
                continue
            payload = line[5:].strip()
            if payload == '[DONE]':
                if finish_reason != 'stop':
                    raise ValueError('DeepSeek stream did not finish normally')
                yield {'done': True, 'prompt_eval_count': input_tokens}
                return
            event = json.loads(payload)
            if event.get('error'):
                raise ValueError('DeepSeek returned an error event')
            usage = event.get('usage')
            if isinstance(usage, dict):
                input_tokens = usage.get('prompt_tokens')
            choices = event.get('choices') or []
            if choices:
                choice = choices[0]
                finish_reason = choice.get('finish_reason') or finish_reason
                content = (choice.get('delta') or {}).get('content')
                if content:
                    yield {'message': {'content': content}}
