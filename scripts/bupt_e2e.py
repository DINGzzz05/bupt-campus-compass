# ruff: noqa: RUF001
"""Run against a live campus backend with isolated demonstration accounts."""

import argparse
import json
import time
from datetime import datetime
from uuid import uuid4

import httpx


def signup(client: httpx.Client) -> None:
    user = f'bupt_e2e_{uuid4().hex[:10]}'
    auth = {'username': user, 'password': f'Local!{uuid4().hex}'}
    client.post('/api/auth/register', json={**auth, 'email': f'{user}@example.com'}).raise_for_status()
    client.post('/api/auth/login-json', json=auth).raise_for_status()


def run(base: str, *, require_redis: bool, require_ollama: bool = False) -> dict:
    with (
        httpx.Client(base_url=base, timeout=180, trust_env=False) as client,
        httpx.Client(
            base_url=base,
            timeout=12,
            trust_env=False,
        ) as outsider,
    ):
        signup(client)
        signup(outsider)
        with client.stream('POST', '/api/chat/stream', json={'content': '北邮本科选课入口在哪里'}) as response:
            response.raise_for_status()
            request_id = response.headers['x-request-id']
            events = [json.loads(line[6:]) for line in response.iter_lines() if line.startswith('data: ')]
        assert events[0]['type'] == 'status'
        assert events[-1]['type'] == 'done'
        done = events[-1]
        assert done['sources'], done['bupt_trace']
        assert done['sources'][0]['kb_number'] == 'bupt-academic-system'
        assert done['bupt_trace']['request_id'] == request_id
        if require_ollama:
            assert done['bupt_trace']['generation'] == 'ollama', done['bupt_trace']
            assert done['bupt_trace']['retrieval'] == 'bm25_chroma'
            assert sum(event['type'] == 'token' for event in events) > 1
        session = done['session_id']
        prefix = f'/api/bupt/sessions/{session}'
        trace_path = f"{prefix}/runs/{done['bupt_trace']['run_id']}"
        trace = client.get(trace_path).raise_for_status().json()
        assert [step['agent'] for step in trace['artifacts']] == ['domain', 'risk', 'memory', 'retrieval', 'review']
        assert trace['status'] == 'completed'
        assert datetime.fromisoformat(trace['started_at']) <= datetime.fromisoformat(trace['finished_at'])
        if require_ollama:
            measured = {entry['purpose']: entry for entry in trace['model_attempts']}
            assert set(measured) == {'route', 'risk', 'answer'}
            assert all(item['outcome'] == 'ok' and item['input_tokens'] for item in measured.values())
        assert outsider.get(trace_path).status_code == 404
        if require_redis:
            assert trace['artifacts'][2]['window'].startswith('redis_')

        questions = ('北邮校外怎么查图书馆电子资源', '那入口呢', '沙河校区校园网怎么连')
        for question in questions:
            result = client.post('/api/chat/chat', json={'session_id': session, 'content': question}).raise_for_status().json()
            metadata = result['assistant_message']['metadata']
            if question == '那入口呢':
                assert metadata['sources'], metadata['bupt_trace']
                assert metadata['sources'][0]['kb_number'] == 'bupt-library-remote'
        snapshot_id = metadata['bupt_trace']['agents'][2]['snapshot_id']
        assert snapshot_id

        for operation, value in (('confirm', '沙河'), ('correct', '海淀'), ('forget', None)):
            changed = client.post(f'{prefix}/memory', json={'operation': operation, 'key': '校区', 'value': value})
            details = changed.raise_for_status().json()
            assert details['facts'].get('校区') == value
        assert client.post(f'{prefix}/memory', json={'operation': 'clear'}).raise_for_status().json()['revision'] == 4
        assert outsider.get(f'{prefix}/memory').status_code == 404
        assert client.get(f'/api/chat/sessions/{session}').raise_for_status().json()['messages']

        check_support(client, outsider, session, prefix)
        client.delete(f'/api/chat/sessions/{session}').raise_for_status()
        return {
            'http_e2e': 'passed',
            'sse_generation': done['bupt_trace']['generation'],
            'retrieval': done['bupt_trace']['retrieval'],
            'memory_window': trace['artifacts'][2]['window'],
            'confirmed_job_completed': True,
            'ownership_checked': True,
        }


def check_support(client: httpx.Client, outsider: httpx.Client, session: int, prefix: str) -> None:
    result = client.post(f'/api/chat/sessions/{session}/messages', json={'content': '我要提交支持请求'}).raise_for_status().json()
    trace_id = result['assistant_message']['metadata']['bupt_trace']['run_id']
    assert result['assistant_message']['metadata']['bupt_trace']['generation'] == 'confirmation_required'
    assert client.post(f'{prefix}/support/draft', json={'summary': '联系邮箱 person@example.com'}).status_code == 422
    draft = client.post(f'{prefix}/support/draft', json={'summary': '沙河校园无线网络连接不稳定，需要查看排查流程'}).raise_for_status().json()
    assert client.get(f'{prefix}/support').raise_for_status().json() == []
    approval = {'confirmation': draft['confirmation'], 'confirmed': True}
    assert client.post(f'{prefix}/support/confirm', json={**approval, 'confirmed': False}).status_code == 422
    assert outsider.post(f'{prefix}/support/confirm', json=approval).status_code == 404
    task_ids = {client.post(f'{prefix}/support/confirm', json=approval).raise_for_status().json()['task_id'] for _ in range(2)}
    assert len(task_ids) == 1
    task_id = task_ids.pop()
    for _ in range(20):
        task = client.get(f'{prefix}/support/{task_id}').raise_for_status().json()
        if task['status'] == 'completed':
            break
        time.sleep(0.25)
    assert task['receipt'] == f'BUPT-{task_id}'
    assert client.get(f'{prefix}/runs/{trace_id}').raise_for_status().json()['actions'][0]['task_id'] == task_id


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--base', default='http://127.0.0.1:8000')
    parser.add_argument('--require-redis', action='store_true')
    parser.add_argument('--require-ollama', action='store_true')
    args = parser.parse_args()
    print(json.dumps(run(args.base, require_redis=args.require_redis, require_ollama=args.require_ollama), indent=2))


if __name__ == '__main__':
    main()
