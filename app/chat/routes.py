"""Chat page and streaming endpoint."""
from __future__ import annotations

import json
import logging

from flask import (
    Blueprint, Response, current_app, jsonify, render_template, request,
)

from app.chat.openrouter import OpenRouterClient
from app.chat.orchestrator import run as orchestrator_run
from app.routes import login_required

log = logging.getLogger(__name__)

bp = Blueprint('chat', __name__)


_MODEL_LABELS = {
    'anthropic/claude-sonnet-4': 'Claude Sonnet 4',
    'anthropic/claude-sonnet-4.5': 'Claude Sonnet 4.5',
    'anthropic/claude-sonnet-4.6': 'Claude Sonnet 4.6',
    'anthropic/claude-opus-4': 'Claude Opus 4',
    'anthropic/claude-opus-4.1': 'Claude Opus 4.1',
    'anthropic/claude-opus-4.5': 'Claude Opus 4.5',
    'anthropic/claude-opus-4.6': 'Claude Opus 4.6',
    'anthropic/claude-opus-4.6-fast': 'Claude Opus 4.6 (Fast)',
    'anthropic/claude-opus-4.7': 'Claude Opus 4.7',
    'anthropic/claude-opus-4.7-fast': 'Claude Opus 4.7 (Fast)',
    'openai/gpt-4o': 'GPT-4o',
    'openai/gpt-5': 'GPT-5',
    'openai/gpt-5-pro': 'GPT-5 Pro',
    'openai/gpt-5.1': 'GPT-5.1',
    'openai/gpt-5.2': 'GPT-5.2',
    'openai/gpt-5.2-pro': 'GPT-5.2 Pro',
    'openai/gpt-5.5': 'GPT-5.5',
    'openai/gpt-5.5-pro': 'GPT-5.5 Pro',
    'openai/o1': 'OpenAI o1',
    'openai/o3': 'OpenAI o3',
    'openai/o3-pro': 'OpenAI o3 Pro',
    'openai/o4-mini-high': 'OpenAI o4-mini High',
    'google/gemini-2.5-pro': 'Gemini 2.5 Pro',
    'google/gemini-2.5-flash': 'Gemini 2.5 Flash',
    'x-ai/grok-4.3': 'Grok 4.3',
    'x-ai/grok-4.20': 'Grok 4.20',
}


def _label_for(slug: str) -> str:
    if slug in _MODEL_LABELS:
        return _MODEL_LABELS[slug]
    return slug.split('/')[-1].replace('-', ' ').title()


def _allowed_models(config) -> list[str]:
    """Allowed model list, with the configured default guaranteed present."""
    models = list(config.get('CHAT_MODELS') or [])
    default = config.get('OPENROUTER_MODEL', '')
    if default and default not in models:
        models = [default, *models]
    return models


def _make_client(app, model: str) -> OpenRouterClient:
    return OpenRouterClient(
        api_key=app.config['OPENROUTER_API_KEY'],
        model=model,
        base_url=app.config['OPENROUTER_BASE_URL'],
    )


@bp.route('/chat')
@login_required
def chat_page():
    allowed = _allowed_models(current_app.config)
    default = current_app.config.get('OPENROUTER_MODEL', '')
    return render_template(
        'chat.html',
        api_key_set=bool(current_app.config.get('OPENROUTER_API_KEY')),
        default_model=default,
        models=[(slug, _label_for(slug)) for slug in allowed],
    )


@bp.route('/api/chat/stream', methods=['POST'])
@login_required
def chat_stream():
    if not current_app.config.get('OPENROUTER_API_KEY'):
        return jsonify({'error': 'OPENROUTER_API_KEY not configured'}), 503

    body = request.get_json(silent=True) or {}
    messages = body.get('messages') or []
    if not isinstance(messages, list):
        return jsonify({'error': 'messages must be a list'}), 400

    allowed = _allowed_models(current_app.config)
    requested_model = body.get('model') or current_app.config['OPENROUTER_MODEL']
    if requested_model not in allowed:
        return jsonify({'error': f'model {requested_model!r} is not allowed'}), 400

    app = current_app._get_current_object()
    client = _make_client(app, requested_model)
    max_iter = app.config.get('CHAT_MAX_ITERATIONS', 10)

    def generate():
        try:
            with app.app_context():
                for name, payload in orchestrator_run(
                    messages=messages, client=client, max_iterations=max_iter,
                ):
                    yield _format_sse(name, payload)
        except Exception as exc:  # noqa: BLE001 — surface to UI
            log.exception('chat stream failed')
            yield _format_sse('error', {'message': str(exc)})
            yield _format_sse('done', {'stop_reason': 'error'})

    return Response(generate(), mimetype='text/event-stream')


def _format_sse(event: str, payload: dict) -> str:
    return f'event: {event}\ndata: {json.dumps(payload)}\n\n'
