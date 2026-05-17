"""Thin client over OpenRouter's OpenAI-compatible chat/completions endpoint."""
from __future__ import annotations

import json
from typing import Iterator

import httpx


class OpenRouterClient:
    def __init__(
        self,
        api_key: str,
        model: str,
        base_url: str = 'https://openrouter.ai/api/v1',
        http_client: httpx.Client | None = None,
        timeout: float = 60.0,
    ):
        if not api_key:
            raise ValueError('OPENROUTER_API_KEY is not set')
        self.api_key = api_key
        self.model = model
        self.base_url = base_url.rstrip('/')
        self._client = http_client or httpx.Client(timeout=timeout)

    def stream(self, messages: list[dict], tools: list[dict]) -> Iterator[dict]:
        """Yield normalized events parsed from OpenRouter's SSE stream."""
        payload = {
            'model': self.model,
            'messages': messages,
            'stream': True,
        }
        if tools:
            payload['tools'] = tools
            payload['tool_choice'] = 'auto'

        with self._client.stream(
            'POST', f'{self.base_url}/chat/completions',
            headers={
                'Authorization': f'Bearer {self.api_key}',
                'Content-Type': 'application/json',
            },
            json=payload,
        ) as response:
            response.raise_for_status()
            for line in response.iter_lines():
                if not line:
                    continue
                if line.startswith(':'):
                    continue  # SSE comment / keep-alive
                if not line.startswith('data: '):
                    continue
                data = line[len('data: '):]
                if data == '[DONE]':
                    break
                try:
                    chunk = json.loads(data)
                except json.JSONDecodeError:
                    continue
                yield from self._parse_chunk(chunk)

    @staticmethod
    def _parse_chunk(chunk: dict) -> Iterator[dict]:
        choices = chunk.get('choices') or []
        if not choices:
            return
        choice = choices[0]
        delta = choice.get('delta') or {}

        if 'content' in delta and delta['content']:
            yield {'type': 'text_delta', 'text': delta['content']}

        for call in delta.get('tool_calls') or []:
            fn = call.get('function') or {}
            yield {
                'type': 'tool_call_delta',
                'index': call.get('index', 0),
                'id': call.get('id'),
                'name': fn.get('name'),
                'arguments_delta': fn.get('arguments', ''),
            }

        finish = choice.get('finish_reason')
        if finish:
            yield {'type': 'stop', 'reason': finish}
