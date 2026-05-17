"""Read-only typed tools the LLM can call to inspect transaction data.

Each tool is a plain Python function. Argument shapes are described by
Pydantic models so we can both validate LLM-supplied args and generate
the JSON schema that OpenRouter expects.
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import date
from typing import Any, Callable

from pydantic import BaseModel, ValidationError
from sqlalchemy import func

from app.models import db, Transaction


# ── Argument models ──────────────────────────────────────────────────────────

class NoArgs(BaseModel):
    pass


# ── Tool implementations ─────────────────────────────────────────────────────

def current_date() -> dict:
    return {'date': date.today().isoformat()}


def get_date_range() -> dict:
    row = db.session.query(
        func.min(Transaction.date), func.max(Transaction.date)
    ).filter_by(removed=False).one()
    earliest, latest = row
    return {
        'earliest': earliest.isoformat() if earliest else None,
        'latest': latest.isoformat() if latest else None,
    }


# ── Registry ─────────────────────────────────────────────────────────────────

@dataclass(frozen=True)
class Tool:
    name: str
    description: str
    args_model: type[BaseModel]
    func: Callable[..., dict]


TOOLS: dict[str, Tool] = {
    'current_date': Tool(
        name='current_date',
        description="Today's date in ISO format. Use to resolve relative dates like 'this month'.",
        args_model=NoArgs,
        func=lambda: current_date(),
    ),
    'get_date_range': Tool(
        name='get_date_range',
        description='Earliest and latest transaction dates available in the database.',
        args_model=NoArgs,
        func=lambda: get_date_range(),
    ),
}


def openai_schemas() -> list[dict]:
    """OpenAI/OpenRouter-shaped tool schemas for every registered tool."""
    out = []
    for tool in TOOLS.values():
        out.append({
            'type': 'function',
            'function': {
                'name': tool.name,
                'description': tool.description,
                'parameters': tool.args_model.model_json_schema(),
            },
        })
    return out


def dispatch(name: str, args: dict[str, Any]) -> dict:
    """Validate args and execute the tool, or return an error dict."""
    tool = TOOLS.get(name)
    if tool is None:
        return {'error': f'unknown tool: {name}'}
    try:
        validated = tool.args_model.model_validate(args or {})
    except ValidationError as exc:
        return {'error': 'invalid arguments', 'detail': exc.errors()}
    try:
        return tool.func(**validated.model_dump())
    except Exception as exc:  # noqa: BLE001 — surfaced to LLM, logged in orchestrator
        return {'error': 'internal', 'type': type(exc).__name__, 'message': str(exc)}
