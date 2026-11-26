# ruff: noqa: RUF001
import httpx
import pytest

from backend.app.services import bupt_knowledge as campus


def test_bm25_returns_official_source_and_abstains(monkeypatch):
    monkeypatch.setattr(campus.settings, 'BUPT_OLLAMA_ENABLED', False)
    documents, trace = campus.search('北邮的图书馆电子资源怎么在校外访问？')
    assert documents[0].metadata['kb_number'] == 'bupt-library-remote'
    assert documents[0].metadata['kb_url'].startswith('https://libportal.bupt.edu.cn/')
    assert len(documents[0].metadata['content_sha256']) == 64
    assert trace['retrieval'] == 'bm25'
    missing, _ = campus.search('火星的卫星叫什么名字？')
    assert campus.answer('火星的卫星叫什么名字？', missing) == (campus.NO_EVIDENCE, 'no_evidence')


def test_ollama_outage_returns_verified_excerpts(tmp_path, monkeypatch):
    def offline(*args, **kwargs):
        raise httpx.ConnectError('simulated outage')

    monkeypatch.setattr(campus.settings, 'BUPT_OLLAMA_ENABLED', True)
    monkeypatch.setattr(campus.settings, 'BUPT_CHROMA_PATH', str(tmp_path))
    monkeypatch.setattr(campus, '_ollama', offline)
    documents, trace = campus.search('毕业去向登记怎么审核')
    message, generation = campus.answer('毕业去向登记怎么审核', documents)
    assert trace['retrieval'] == 'bm25_fallback'
    assert generation == 'extractive_fallback'
    assert documents[0].page_content in message


def test_chroma_and_bm25_rank_fusion(tmp_path, monkeypatch):
    pytest.importorskip('chromadb')
    monkeypatch.setattr(campus.settings, 'BUPT_OLLAMA_ENABLED', True)
    monkeypatch.setattr(campus.settings, 'BUPT_CHROMA_PATH', str(tmp_path))

    def ollama(path, payload, timeout):
        if path == 'embed':
            return {'embeddings': [[1, 0] if '大创' in text else [0, 1] for text in payload['input']]}
        return {'message': {'content': '请查看教务部学生服务页提供的大创平台入口。'}, 'done': True}

    monkeypatch.setattr(campus, '_ollama', ollama)
    documents, trace = campus.search('北邮大创从哪儿进')
    assert documents[0].metadata['kb_number'] == 'bupt-innovation'
    assert trace['lexical_candidate_ids'][0] == trace['vector_candidate_ids'][0] == 'bupt-innovation'
    assert trace['retrieval'] == 'bm25_chroma'
    assert campus.answer('北邮大创从哪儿进', documents)[1] == 'ollama'
