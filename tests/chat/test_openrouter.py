import httpx
import pytest

from app.chat.openrouter import OpenRouterClient


def _make_client(sse_body: str) -> OpenRouterClient:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200,
            headers={'content-type': 'text/event-stream'},
            content=sse_body.encode(),
        )
    transport = httpx.MockTransport(handler)
    return OpenRouterClient(
        api_key='test-key',
        model='test-model',
        base_url='https://test.example/api/v1',
        http_client=httpx.Client(transport=transport),
    )


def test_stream_text_only():
    body = (
        'data: {"choices":[{"delta":{"content":"Hello "}}]}\n\n'
        'data: {"choices":[{"delta":{"content":"world"}}]}\n\n'
        'data: {"choices":[{"delta":{},"finish_reason":"stop"}]}\n\n'
        'data: [DONE]\n\n'
    )
    events = list(_make_client(body).stream(messages=[{'role':'user','content':'hi'}], tools=[]))
    assert events == [
        {'type': 'text_delta', 'text': 'Hello '},
        {'type': 'text_delta', 'text': 'world'},
        {'type': 'stop', 'reason': 'stop'},
    ]


def test_stream_tool_call():
    body = (
        'data: {"choices":[{"delta":{"tool_calls":[{"index":0,"id":"call_1","function":{"name":"current_date","arguments":""}}]}}]}\n\n'
        'data: {"choices":[{"delta":{"tool_calls":[{"index":0,"function":{"arguments":"{}"}}]}}]}\n\n'
        'data: {"choices":[{"delta":{},"finish_reason":"tool_calls"}]}\n\n'
        'data: [DONE]\n\n'
    )
    events = list(_make_client(body).stream(messages=[], tools=[]))
    assert events == [
        {'type': 'tool_call_delta', 'index': 0, 'id': 'call_1',
         'name': 'current_date', 'arguments_delta': ''},
        {'type': 'tool_call_delta', 'index': 0, 'id': None,
         'name': None, 'arguments_delta': '{}'},
        {'type': 'stop', 'reason': 'tool_calls'},
    ]


def test_stream_skips_keepalive_comments():
    body = (
        ': openrouter keep-alive\n\n'
        'data: {"choices":[{"delta":{"content":"ok"}}]}\n\n'
        'data: [DONE]\n\n'
    )
    events = list(_make_client(body).stream(messages=[], tools=[]))
    assert events == [{'type': 'text_delta', 'text': 'ok'}]
