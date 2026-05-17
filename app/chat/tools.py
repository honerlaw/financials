"""Read-only typed tools the LLM can call to inspect transaction data.

Each tool is a plain Python function. Argument shapes are described by
Pydantic models so we can both validate LLM-supplied args and generate
the JSON schema that OpenRouter expects.
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import date
from typing import Any, Callable, Literal

from pydantic import BaseModel, Field, ValidationError
from sqlalchemy import func

from app.models import db, Transaction


# ── Argument models ──────────────────────────────────────────────────────────

class NoArgs(BaseModel):
    pass


class QueryTransactionsArgs(BaseModel):
    start_date: date = Field(description='Inclusive start date YYYY-MM-DD')
    end_date: date = Field(description='Inclusive end date YYYY-MM-DD')
    institution_id: int | None = Field(default=None)
    category: str | None = Field(default=None)
    merchant_contains: str | None = Field(
        default=None,
        description='Case-insensitive substring match against description or merchant_name',
    )
    min_amount: float | None = Field(default=None)
    max_amount: float | None = Field(default=None)
    limit: int = Field(default=200, ge=1, le=200)


class AggregateTransactionsArgs(BaseModel):
    start_date: date = Field(description='Inclusive start date YYYY-MM-DD')
    end_date: date = Field(description='Inclusive end date YYYY-MM-DD')
    group_by: Literal['month', 'category', 'merchant', 'institution']
    metric: Literal['sum', 'abs_sum', 'count', 'avg', 'net']
    institution_id: int | None = Field(default=None)
    category: str | None = Field(default=None)
    merchant_contains: str | None = Field(
        default=None,
        description='Case-insensitive substring match against description or merchant_name',
    )


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


def list_institutions() -> dict:
    from app.models import Institution
    rows = db.session.query(Institution).order_by(Institution.name).all()
    return {
        'institutions': [
            {'id': r.id, 'name': r.name, 'slug': r.slug, 'status': r.status}
            for r in rows
        ]
    }


def query_transactions(
    start_date: date, end_date: date,
    institution_id: int | None = None,
    category: str | None = None,
    merchant_contains: str | None = None,
    min_amount: float | None = None,
    max_amount: float | None = None,
    limit: int = 200,
) -> dict:
    from flask import current_app
    cap = min(limit, current_app.config.get('CHAT_QUERY_ROW_LIMIT', 200))

    q = db.session.query(Transaction).filter(
        Transaction.removed.is_(False),
        Transaction.date >= start_date,
        Transaction.date <= end_date,
    )
    if institution_id is not None:
        q = q.filter(Transaction.institution_id == institution_id)
    if category is not None:
        q = q.filter(Transaction.category == category)
    if merchant_contains is not None:
        like = f'%{merchant_contains.lower()}%'
        q = q.filter(
            func.lower(Transaction.description).like(like)
            | func.lower(Transaction.merchant_name).like(like)
        )
    if min_amount is not None:
        q = q.filter(Transaction.amount >= min_amount)
    if max_amount is not None:
        q = q.filter(Transaction.amount <= max_amount)

    q = q.order_by(Transaction.date.desc(), Transaction.id.desc())
    rows = q.limit(cap + 1).all()
    truncated = len(rows) > cap
    rows = rows[:cap]
    return {
        'rows': [
            {
                'id': r.id,
                'date': r.date.isoformat(),
                'description': r.description,
                'merchant_name': r.merchant_name,
                'amount': float(r.amount),
                'category': r.category,
                'institution_id': r.institution_id,
            }
            for r in rows
        ],
        'count': len(rows),
        'truncated': truncated,
    }


def aggregate_transactions(
    start_date: date, end_date: date,
    group_by: str, metric: str,
    institution_id: int | None = None,
    category: str | None = None,
    merchant_contains: str | None = None,
) -> dict:
    from app.models import Institution

    q = db.session.query(Transaction).filter(
        Transaction.removed.is_(False),
        Transaction.date >= start_date,
        Transaction.date <= end_date,
    )
    if institution_id is not None:
        q = q.filter(Transaction.institution_id == institution_id)
    if category is not None:
        q = q.filter(Transaction.category == category)
    if merchant_contains is not None:
        like = f'%{merchant_contains.lower()}%'
        q = q.filter(
            func.lower(Transaction.description).like(like)
            | func.lower(Transaction.merchant_name).like(like)
        )

    inst_names = {i.id: i.name for i in db.session.query(Institution).all()}

    buckets: dict[Any, list[float]] = {}
    for tx in q.all():
        amt = float(tx.amount)
        if group_by == 'month':
            key = tx.date.strftime('%Y-%m')
        elif group_by == 'category':
            key = tx.category or '(uncategorized)'
        elif group_by == 'merchant':
            key = tx.merchant_name or tx.description
        elif group_by == 'institution':
            key = inst_names.get(tx.institution_id, str(tx.institution_id))
        # group_by already constrained by Pydantic Literal
        buckets.setdefault(key, []).append(amt)

    groups = []
    for key, amounts in buckets.items():
        if metric == 'sum':
            value = sum(amounts)
        elif metric == 'abs_sum':
            value = sum(abs(a) for a in amounts if a < 0)
        elif metric == 'count':
            value = len(amounts)
        elif metric == 'avg':
            value = sum(amounts) / len(amounts) if amounts else 0
        elif metric == 'net':
            value = sum(amounts)
        groups.append({'key': key, 'value': round(value, 2)})

    groups.sort(key=lambda g: g['key'] if group_by == 'month' else -abs(g['value']))
    return {'groups': groups}


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
    'list_institutions': Tool(
        name='list_institutions',
        description='Connected bank institutions (id, name, slug, status).',
        args_model=NoArgs,
        func=lambda: list_institutions(),
    ),
    'query_transactions': Tool(
        name='query_transactions',
        description=(
            'Filtered list of transactions. Returns up to limit rows '
            '(hard cap enforced server-side) and a truncated flag.'
        ),
        args_model=QueryTransactionsArgs,
        func=query_transactions,
    ),
    'aggregate_transactions': Tool(
        name='aggregate_transactions',
        description=(
            'Aggregate transactions over a date range. '
            'group_by: month|category|merchant|institution. '
            'metric: sum (signed), abs_sum (total spend as positive), '
            'count, avg, net (= sum).'
        ),
        args_model=AggregateTransactionsArgs,
        func=aggregate_transactions,
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
