"""Bill detection and monthly payment-status tracking.

A "bill" is any recurring outflow stream — utilities, rent, card payments, etc.
Inflows (paychecks, refunds) are excluded. Detection reuses the same
cadence-based grouping as subscriptions.py; payment status is a per-month
overlay computed from raw transaction dates.
"""

import calendar
from datetime import date, timedelta

from app.subscriptions import (
    _build_stream,
    _group_transactions,
)

PAYMENT_WINDOW = 6  # days around expected day-of-month to match a payment

_STATUS_ORDER = {'unpaid': 0, 'upcoming': 1, 'paid': 2, 'inactive': 3}


def _expected_day_of_month(txns):
    """Median calendar day across all historical transaction dates."""
    days = sorted(t.date.day for t in txns)
    n = len(days)
    mid = n // 2
    if n % 2:
        return days[mid]
    return (days[mid - 1] + days[mid]) // 2


def _safe_date(year, month, day):
    """Return date(year, month, day), clamping day to the last day of month."""
    last = calendar.monthrange(year, month)[1]
    return date(year, month, min(day, last))


def _payment_status(txns, today):
    """Compute payment status for the current calendar month.

    Returns (status, expected_date) where status is one of:
      'upcoming' — expected date not yet reached (within tolerance)
      'paid'     — a matching transaction found near expected date
      'unpaid'   — expected date has passed with no matching transaction
    """
    expected_day = _expected_day_of_month(txns)
    expected_date = _safe_date(today.year, today.month, expected_day)

    if today < expected_date - timedelta(days=PAYMENT_WINDOW):
        return 'upcoming', expected_date

    matching = [
        t for t in txns
        if t.date.year == today.year
        and t.date.month == today.month
        and abs((t.date - expected_date).days) <= PAYMENT_WINDOW
    ]
    if matching:
        return 'paid', expected_date
    return 'unpaid', expected_date


def detect_bills(transactions, today):
    """Detect recurring outflow streams and compute monthly payment status.

    Returns a list of bill dicts (same shape as detect_subscriptions streams,
    plus 'payment_status' and 'expected_date_this_month'), sorted unpaid-first,
    then upcoming, then paid; within each group by amount magnitude descending.
    """
    live = [t for t in transactions if not t.removed]
    return detect_bills_from_groups(_group_transactions(live), today)


def detect_bills_from_groups(groups, today):
    """Build bills from already-grouped transactions.

    Split out so the persisted merchant-group index can supply the grouping
    (see app/merchant_groups.py). Payment status is recomputed from `today` on
    every call and never cached — a stored status would be wrong the moment the
    month rolled over, with nothing to trigger a refresh.
    """
    bills = []
    for group in groups:
        stream = _build_stream(group, today)
        if stream is None:
            continue
        if stream['is_inflow']:
            continue

        if not stream['active']:
            stream['payment_status'] = 'inactive'
            stream['expected_date_this_month'] = _safe_date(
                today.year, today.month, _expected_day_of_month(group)
            )
        else:
            status, expected_date = _payment_status(group, today)
            stream['payment_status'] = status
            stream['expected_date_this_month'] = expected_date
        bills.append(stream)

    bills.sort(key=lambda b: (_STATUS_ORDER[b['payment_status']], -abs(b['amount'])))
    return bills
