"""LLM↔tool orchestration loop.

Consumes events from an OpenRouter-like client and emits a stream of
(event_name, payload) tuples for the route layer to format as SSE.
"""
from __future__ import annotations

import json
import logging
from typing import Iterator, Protocol

from app.chat import tools as tools_module

log = logging.getLogger(__name__)

SYSTEM_PROMPT = (
    'You are the financial-analysis assistant for a personal-finance app. '
    "You have read-only access to the user's connected bank transactions via tools. "
    'When the user asks a free-form question, decide which tool(s) to call. '
    'Format final answers as markdown with tables where helpful. '
    "Use current_date() if you need to resolve 'this month', 'last quarter', etc. "
    "Don't fabricate data — only state what tools return."
)


class LLMClient(Protocol):
    def stream(self, messages: list[dict], tools: list[dict]) -> Iterator[dict]: ...


def run(
    messages: list[dict],
    client: LLMClient,
    max_iterations: int = 10,
) -> Iterator[tuple[str, dict]]:
    convo: list[dict] = [{'role': 'system', 'content': SYSTEM_PROMPT}, *messages]
    tool_schemas = tools_module.openai_schemas()

    for _ in range(max_iterations):
        assistant_text_parts: list[str] = []
        partial_calls: dict[int, dict] = {}
        stop_reason: str | None = None

        for event in client.stream(messages=convo, tools=tool_schemas):
            etype = event.get('type')
            if etype == 'text_delta':
                assistant_text_parts.append(event['text'])
                yield ('text', {'delta': event['text']})
            elif etype == 'tool_call_delta':
                idx = event['index']
                slot = partial_calls.setdefault(
                    idx, {'id': None, 'name': None, 'arguments': ''}
                )
                if event.get('id'):
                    slot['id'] = event['id']
                if event.get('name'):
                    slot['name'] = event['name']
                slot['arguments'] += event.get('arguments_delta') or ''
            elif etype == 'stop':
                stop_reason = event.get('reason')

        # Append the assistant turn to the conversation.
        assistant_msg: dict = {'role': 'assistant'}
        text = ''.join(assistant_text_parts)
        if text:
            assistant_msg['content'] = text
        if partial_calls:
            assistant_msg['tool_calls'] = [
                {
                    'id': call['id'] or f'call_{idx}',
                    'type': 'function',
                    'function': {
                        'name': call['name'] or '',
                        'arguments': call['arguments'] or '{}',
                    },
                }
                for idx, call in sorted(partial_calls.items())
            ]
        if 'content' in assistant_msg or 'tool_calls' in assistant_msg:
            convo.append(assistant_msg)

        if not partial_calls:
            yield ('done', {'stop_reason': stop_reason or 'stop'})
            return

        # Execute each tool call.
        for idx, call in sorted(partial_calls.items()):
            tool_id = call['id'] or f'call_{idx}'
            name = call['name'] or ''
            try:
                args = json.loads(call['arguments'] or '{}')
            except json.JSONDecodeError:
                args = {}

            yield ('tool_start', {'id': tool_id, 'name': name, 'args': args})
            try:
                result = tools_module.dispatch(name, args)
            except Exception as exc:  # defensive — dispatch already catches
                log.exception('tool dispatch crashed: %s', name)
                result = {'error': 'internal', 'message': str(exc)}
            yield ('tool_result', {'id': tool_id, 'name': name, 'result': result})

            convo.append({
                'role': 'tool',
                'tool_call_id': tool_id,
                'content': json.dumps(result),
            })

    yield ('error', {'message': f'max iterations ({max_iterations}) reached'})
    yield ('done', {'stop_reason': 'max_iterations'})
