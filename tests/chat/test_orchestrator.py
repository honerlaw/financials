import json

import pytest

from app.chat.orchestrator import run


class FakeClient:
    """LLM client that replays pre-canned event streams per call."""

    def __init__(self, streams: list[list[dict]]):
        self._streams = list(streams)
        self.calls: list[dict] = []

    def stream(self, messages, tools):
        self.calls.append({'messages': list(messages), 'tools': tools})
        assert self._streams, 'FakeClient ran out of canned streams'
        for ev in self._streams.pop(0):
            yield ev


def _collect(gen):
    return [(name, dict(payload)) for name, payload in gen]


def test_text_only_turn(app):
    fake = FakeClient([[
        {'type': 'text_delta', 'text': 'Hello'},
        {'type': 'text_delta', 'text': ' world'},
        {'type': 'stop', 'reason': 'stop'},
    ]])
    with app.app_context():
        events = _collect(run(
            messages=[{'role': 'user', 'content': 'hi'}],
            client=fake, max_iterations=5,
        ))
    assert events == [
        ('text', {'delta': 'Hello'}),
        ('text', {'delta': ' world'}),
        ('done', {'stop_reason': 'stop'}),
    ]
    assert len(fake.calls) == 1


def test_single_tool_call_then_answer(app):
    fake = FakeClient([
        [
            {'type': 'tool_call_delta', 'index': 0, 'id': 'call_a',
             'name': 'current_date', 'arguments_delta': ''},
            {'type': 'tool_call_delta', 'index': 0, 'id': None,
             'name': None, 'arguments_delta': '{}'},
            {'type': 'stop', 'reason': 'tool_calls'},
        ],
        [
            {'type': 'text_delta', 'text': 'Today is fine'},
            {'type': 'stop', 'reason': 'stop'},
        ],
    ])
    with app.app_context():
        events = _collect(run(
            messages=[{'role': 'user', 'content': 'what day is it'}],
            client=fake, max_iterations=5,
        ))
    names = [name for name, _ in events]
    assert names == ['tool_start', 'tool_result', 'text', 'done']

    tool_start = events[0][1]
    assert tool_start['name'] == 'current_date'
    assert tool_start['args'] == {}
    tool_result = events[1][1]
    assert 'date' in tool_result['result']

    # second call to the LLM must include the tool call + tool result
    second_msgs = fake.calls[1]['messages']
    assert second_msgs[-1]['role'] == 'tool'
    assert second_msgs[-1]['tool_call_id'] == 'call_a'


def test_iteration_cap(app):
    forever = [
        {'type': 'tool_call_delta', 'index': 0, 'id': 'c', 'name': 'current_date',
         'arguments_delta': '{}'},
        {'type': 'stop', 'reason': 'tool_calls'},
    ]
    fake = FakeClient([list(forever) for _ in range(10)])
    with app.app_context():
        events = _collect(run(
            messages=[{'role': 'user', 'content': 'loop'}],
            client=fake, max_iterations=2,
        ))
    assert events[-2][0] == 'error'
    assert 'max iterations' in events[-2][1]['message']
    assert events[-1][0] == 'done'


def test_invalid_tool_args_surfaced_to_llm(app):
    fake = FakeClient([
        [
            {'type': 'tool_call_delta', 'index': 0, 'id': 'bad',
             'name': 'query_transactions',
             'arguments_delta': '{"start_date": "not-a-date", "end_date": "2026-03-31"}'},
            {'type': 'stop', 'reason': 'tool_calls'},
        ],
        [
            {'type': 'text_delta', 'text': 'sorry'},
            {'type': 'stop', 'reason': 'stop'},
        ],
    ])
    with app.app_context():
        events = _collect(run(
            messages=[{'role': 'user', 'content': 'bad'}],
            client=fake, max_iterations=5,
        ))
    tool_result = [e for n, e in events if n == 'tool_result'][0]
    assert 'error' in tool_result['result']
