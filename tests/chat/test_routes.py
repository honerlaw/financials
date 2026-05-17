import json

import pytest


@pytest.fixture
def fake_llm_client(monkeypatch):
    """Replace the OpenRouterClient factory used by the chat route."""

    class FakeClient:
        def __init__(self, *_, **__):
            pass

        def stream(self, messages, tools):
            yield {'type': 'text_delta', 'text': 'pong'}
            yield {'type': 'stop', 'reason': 'stop'}

    monkeypatch.setattr('app.chat.routes._make_client', lambda app: FakeClient())
    return FakeClient


def test_chat_page_renders(auth_client):
    resp = auth_client.get('/chat')
    assert resp.status_code == 200
    assert b'chat' in resp.data.lower()


def test_chat_page_redirects_when_unauthenticated(client):
    resp = client.get('/chat')
    assert resp.status_code in (302, 303)


def test_stream_requires_auth(client):
    resp = client.post('/api/chat/stream', json={'messages': []})
    assert resp.status_code in (302, 303)


def test_stream_returns_sse(auth_client, fake_llm_client):
    resp = auth_client.post(
        '/api/chat/stream',
        json={'messages': [{'role': 'user', 'content': 'ping'}]},
    )
    assert resp.status_code == 200
    assert resp.mimetype == 'text/event-stream'

    body = resp.get_data(as_text=True)
    events = _parse_sse(body)
    types = [e['event'] for e in events]
    assert 'text' in types
    assert 'done' in types
    text_payloads = [e['data'] for e in events if e['event'] == 'text']
    assert any('"delta": "pong"' in p or '"delta":"pong"' in p for p in text_payloads)


def test_stream_disabled_without_api_key(auth_client, app):
    app.config['OPENROUTER_API_KEY'] = ''
    resp = auth_client.post(
        '/api/chat/stream',
        json={'messages': [{'role': 'user', 'content': 'ping'}]},
    )
    assert resp.status_code == 503


def _parse_sse(body: str) -> list[dict]:
    events = []
    current = {}
    for line in body.splitlines():
        if line == '':
            if current:
                events.append(current)
                current = {}
            continue
        if ': ' in line:
            field, _, value = line.partition(': ')
            current[field] = current.get(field, '') + value
    if current:
        events.append(current)
    return events
