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


def _make_client(app) -> OpenRouterClient:
    return OpenRouterClient(
        api_key=app.config['OPENROUTER_API_KEY'],
        model=app.config['OPENROUTER_MODEL'],
        base_url=app.config['OPENROUTER_BASE_URL'],
    )


@bp.route('/chat')
@login_required
def chat_page():
    return render_template(
        'chat.html',
        api_key_set=bool(current_app.config.get('OPENROUTER_API_KEY')),
        model=current_app.config.get('OPENROUTER_MODEL', ''),
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

    app = current_app._get_current_object()
    client = _make_client(app)
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
