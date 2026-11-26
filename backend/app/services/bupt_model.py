# ruff: noqa: RUF001
"""Ollama routing and per-stage circuit breakers."""

import json
from collections.abc import AsyncIterator
from dataclasses import dataclass, field
from threading import Lock
from time import monotonic, perf_counter

import httpx
from pydantic import SecretStr

from backend.app.core.config_manager import settings
from backend.app.services import bupt_deepseek


@dataclass
class CircuitBreaker:
    threshold: int = 2
    cooldown: float = 20
    failures: int = 0
    opened: float | None = None
    probe: bool = False
    generation: int = 0
    lock: Lock = field(default_factory=Lock)

    def acquire(self) -> tuple[int, bool] | None:
        with self.lock:
            if self.opened is None:
                return self.generation, False
            if self.probe or monotonic() - self.opened < self.cooldown:
                return None
            self.probe = True
            return self.generation, True

    def finish(self, permit: tuple[int, bool], success: bool | None) -> None:
        with self.lock:
            generation, is_probe = permit
            if generation != self.generation:
                return
            if is_probe:
                self.probe = False
            if success is None:
                return
            if success:
                self.failures, self.opened = 0, None
                return
            self.failures += 1
            if self.failures >= self.threshold:
                self.opened = monotonic()
                self.generation += 1


_BREAKERS = {purpose: CircuitBreaker() for purpose in ('route', 'risk', 'summary', 'answer')}


class ModelRouter:
    def __init__(self, deepseek_key: SecretStr | None = None) -> None:
        self.attempts: list[dict] = []
        self._deepseek_key = deepseek_key

    def provider(self, purpose: str) -> str | None:
        if purpose == 'answer' and self._deepseek_key is not None:
            return 'deepseek'
        return 'ollama' if settings.BUPT_OLLAMA_ENABLED else None

    async def text(self, purpose: str, instruction: str, data: str) -> str:
        return ''.join([token async for token in self.stream(purpose, instruction, data)])

    async def stream(self, purpose: str, instruction: str, data: str) -> AsyncIterator[str]:
        provider = self.provider(purpose)
        if provider is None:
            return
        # Browser-provided keys are isolated to each request, including authentication failures.
        breaker = _BREAKERS[purpose] if provider == 'ollama' else None
        permit = breaker.acquire() if breaker else None
        if breaker and permit is None:
            self._record(purpose, 'circuit_open', 0)
            return
        started = perf_counter()
        outcome, failure, input_tokens, success = 'cancelled', None, None, None
        try:
            sent = False
            events = (
                bupt_deepseek.chat_events(self._deepseek_key, instruction, data)
                if provider == 'deepseek' and self._deepseek_key is not None
                else self._events(purpose, instruction, data)
            )
            async for event in events:
                if event.get('error'):
                    raise ValueError('Ollama returned an error event')
                token = event.get('message', {}).get('content', '')
                if token and (sent or token.strip()):
                    sent = True
                    yield token
                if event.get('done') is True and sent:
                    if purpose == 'answer' and event.get('done_reason') == 'length':
                        raise ValueError('answer exceeded its token budget')
                    outcome, success = 'ok', True
                    input_tokens = event.get('prompt_eval_count')
                    return
            raise ValueError('missing final model event or empty response')
        except (httpx.HTTPError, ValueError, TypeError, AttributeError) as exc:
            outcome, success, failure = 'failed', False, type(exc).__name__
            raise
        finally:
            if breaker and permit is not None:
                breaker.finish(permit, success)
            self._record(purpose, outcome, round((perf_counter() - started) * 1000), input_tokens, failure)

    async def _events(self, purpose: str, instruction: str, data: str) -> AsyncIterator[dict]:
        async with (
            httpx.AsyncClient(trust_env=False, timeout=httpx.Timeout(60, connect=3)) as client,
            client.stream(
                'POST',
                f'{settings.BUPT_OLLAMA_URL.rstrip("/")}/api/chat',
                json={
                    'model': settings.BUPT_CHAT_MODEL,
                    'stream': True,
                    'messages': [{'role': 'system', 'content': instruction}, {'role': 'user', 'content': data}],
                    'options': {'temperature': 0, 'num_predict': {'route': 12, 'risk': 12, 'summary': 180, 'answer': 350}[purpose]},
                },
            ) as response,
        ):
            response.raise_for_status()
            async for line in response.aiter_lines():
                if line.strip():
                    yield json.loads(line)

    def _record(self, purpose, outcome, elapsed_ms, input_tokens=None, failure=None):
        self.attempts.append(
            {
                'purpose': purpose,
                'model': bupt_deepseek.MODEL if self.provider(purpose) == 'deepseek' else settings.BUPT_CHAT_MODEL,
                'outcome': outcome,
                'elapsed_ms': elapsed_ms,
                'input_tokens': input_tokens,
                'failure': failure,
            }
        )
