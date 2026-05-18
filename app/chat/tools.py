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
    category: str | None = Field(
        default=None,
        description="Plaid PFC primary category, e.g. 'FOOD_AND_DRINK', 'INCOME', 'TRANSFER_IN'.",
    )
    category_detailed: str | None = Field(
        default=None,
        description=(
            'Plaid PFC detailed category for fine-grained type classification, '
            "e.g. 'INCOME_WAGES', 'TRANSFER_IN_ACCOUNT_TRANSFER', "
            "'FOOD_AND_DRINK_RESTAURANT'."
        ),
    )
    payment_channel: Literal['online', 'in store', 'other'] | None = Field(default=None)
    merchant_contains: str | None = Field(
        default=None,
        description='Case-insensitive substring match against description or merchant_name',
    )
    min_amount: float | None = Field(default=None)
    max_amount: float | None = Field(default=None)
    include_pending: bool = Field(
        default=False,
        description='Pending transactions are excluded by default — they can change or disappear.',
    )
    limit: int = Field(default=200, ge=1, le=200)


class AggregateTransactionsArgs(BaseModel):
    start_date: date = Field(description='Inclusive start date YYYY-MM-DD')
    end_date: date = Field(description='Inclusive end date YYYY-MM-DD')
    group_by: Literal['month', 'category', 'category_detailed', 'merchant', 'institution']
    metric: Literal['sum', 'abs_sum', 'count', 'avg', 'net']
    institution_id: int | None = Field(default=None)
    category: str | None = Field(default=None)
    category_detailed: str | None = Field(default=None)
    merchant_contains: str | None = Field(
        default=None,
        description='Case-insensitive substring match against description or merchant_name',
    )
    include_pending: bool = Field(default=False)


class FindRecurringArgs(BaseModel):
    lookback_months: int = Field(default=6, ge=1, le=24)
    min_occurrences: int = Field(default=2, ge=2)
    amount_tolerance: float = Field(default=0.10, ge=0.0, le=1.0)


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
    category_detailed: str | None = None,
    payment_channel: str | None = None,
    merchant_contains: str | None = None,
    min_amount: float | None = None,
    max_amount: float | None = None,
    include_pending: bool = False,
    limit: int = 200,
) -> dict:
    from flask import current_app
    cap = min(limit, current_app.config.get('CHAT_QUERY_ROW_LIMIT', 200))

    q = db.session.query(Transaction).filter(
        Transaction.removed.is_(False),
        Transaction.date >= start_date,
        Transaction.date <= end_date,
    )
    if not include_pending:
        q = q.filter(Transaction.pending.is_(False))
    if institution_id is not None:
        q = q.filter(Transaction.institution_id == institution_id)
    if category is not None:
        q = q.filter(Transaction.category == category)
    if category_detailed is not None:
        q = q.filter(Transaction.category_detailed == category_detailed)
    if payment_channel is not None:
        q = q.filter(Transaction.payment_channel == payment_channel)
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
                'authorized_date': r.authorized_date.isoformat() if r.authorized_date else None,
                'description': r.description,
                'original_description': r.original_description,
                'merchant_name': r.merchant_name,
                'amount': float(r.amount),
                'iso_currency_code': r.iso_currency_code,
                'category': r.category,
                'category_detailed': r.category_detailed,
                'category_confidence': r.category_confidence,
                'payment_channel': r.payment_channel,
                'transaction_code': r.transaction_code,
                'pending': r.pending,
                'counterparties': r.counterparties,
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
    category_detailed: str | None = None,
    merchant_contains: str | None = None,
    include_pending: bool = False,
) -> dict:
    from app.models import Institution

    q = db.session.query(Transaction).filter(
        Transaction.removed.is_(False),
        Transaction.date >= start_date,
        Transaction.date <= end_date,
    )
    if not include_pending:
        q = q.filter(Transaction.pending.is_(False))
    if institution_id is not None:
        q = q.filter(Transaction.institution_id == institution_id)
    if category is not None:
        q = q.filter(Transaction.category == category)
    if category_detailed is not None:
        q = q.filter(Transaction.category_detailed == category_detailed)
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
        elif group_by == 'category_detailed':
            key = tx.category_detailed or '(uncategorized)'
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


def find_recurring(
    lookback_months: int = 6,
    min_occurrences: int = 2,
    amount_tolerance: float = 0.10,
) -> dict:
    from datetime import timedelta
    from statistics import median, stdev

    end = date.today()
    start = end - timedelta(days=lookback_months * 31)

    rows = db.session.query(Transaction).filter(
        Transaction.removed.is_(False),
        Transaction.date >= start,
        Transaction.date <= end,
    ).all()

    by_merchant: dict[str, list[Transaction]] = {}
    for tx in rows:
        key = tx.merchant_name or tx.description
        by_merchant.setdefault(key, []).append(tx)

    candidates = []
    for merchant, txs in by_merchant.items():
        months = {(t.date.year, t.date.month) for t in txs}
        if len(months) < min_occurrences:
            continue
        amounts = [float(t.amount) for t in txs]
        abs_amounts = [abs(a) for a in amounts]
        mean = sum(abs_amounts) / len(abs_amounts)
        if mean == 0:
            continue
        # Coefficient of variation: stdev / mean
        if len(abs_amounts) > 1:
            cv = stdev(abs_amounts) / mean
        else:
            cv = 0.0
        if cv > amount_tolerance:
            continue
        med = median(amounts)
        candidates.append({
            'merchant': merchant,
            'typical_amount': round(med, 2),
            'occurrences': len(months),
            'months': sorted(f'{y:04d}-{m:02d}' for y, m in months),
            'institution_ids': sorted({t.institution_id for t in txs}),
        })

    candidates.sort(key=lambda c: abs(c['typical_amount']), reverse=True)
    return {'candidates': candidates}


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
            '(hard cap enforced server-side) and a truncated flag. '
            'Each row includes Plaid PFC category (primary + detailed + confidence), '
            'payment_channel, pending flag, authorized_date, original_description, '
            'and counterparties (payer/payee entities) — use these to distinguish '
            'spend vs transfer vs paycheck. Pending transactions excluded by default.'
        ),
        args_model=QueryTransactionsArgs,
        func=query_transactions,
    ),
    'aggregate_transactions': Tool(
        name='aggregate_transactions',
        description=(
            'Aggregate transactions over a date range. '
            'group_by: month|category|category_detailed|merchant|institution. '
            'metric: sum (signed), abs_sum (total spend as positive), '
            'count, avg, net (= sum). '
            'Pending transactions excluded by default.'
        ),
        args_model=AggregateTransactionsArgs,
        func=aggregate_transactions,
    ),
    'find_recurring': Tool(
        name='find_recurring',
        description=(
            'Find recurring transactions: same merchant appearing across N+ '
            'distinct calendar months with amounts within the tolerance of '
            'the median. Returns candidates for the LLM to classify into '
            'bills/subscriptions/transfers.'
        ),
        args_model=FindRecurringArgs,
        func=find_recurring,
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
