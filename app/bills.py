"""Recurring expenses (bills) and recurring income, for the /recurring page.

A "bill" is any recurring outflow stream — utilities, rent, card payments, etc.
"Income" is any recurring inflow stream — paychecks, interest, but also
transfers in and refunds, which are listed but not counted. Detection reuses the
same cadence-based grouping as subscriptions.py; payment status is a per-month
overlay computed from raw transaction dates.

The page's headlines are two monthly totals. Expenses deliberately lean high —
the 75th percentile of the last year's charges — so a variable bill (utilities,
interest) is budgeted nearer its expensive months than its median, while a
fixed-price bill is simply its price. Income leans low — the 25th percentile —
so "left after recurring" errs on the side of less, never more.
"""

import calendar
from collections import defaultdict
from datetime import date, timedelta
from decimal import ROUND_HALF_UP, Decimal

from app.subscriptions import (
    _build_stream,
    _group_transactions,
)

PAYMENT_WINDOW = 6  # days around expected day-of-month to match a payment

_STATUS_ORDER = {'unpaid': 0, 'upcoming': 1, 'paid': 2, 'inactive': 3}

# Charges per month for each cadence, to turn one occurrence into a monthly cost.
MONTHLY_FACTOR = {
    'weekly': Decimal(52) / 12,
    'biweekly': Decimal(26) / 12,
    'monthly': Decimal(1),
    'quarterly': Decimal(1) / 3,
    'annual': Decimal(1) / 12,
}

ESTIMATE_PERCENTILE = Decimal('0.75')  # leans high without letting one spike set it
INCOME_PERCENTILE = Decimal('0.25')    # leans low: never overstate what comes in
ESTIMATE_WINDOW_DAYS = 365             # a full seasonal cycle for utilities

# Annual is excluded from the total: the detector calls two purchases a year
# apart an annual stream, and in real data that sweeps in tax payments and
# one-off purchases that would swamp the monthly total.
_TOTAL_CADENCES = {'weekly', 'biweekly', 'monthly', 'quarterly'}

# A credit-card payment from checking settles the very charges already counted
# on the card, and a transfer moves money rather than spending it. Unlike
# spending.is_spend, other LOAN_PAYMENTS (mortgage, car, student loan) are
# exactly the fixed bills this total is for, so only card payments are excluded.
_TRANSFER_PREFIX = 'TRANSFER'
_CARD_PAYMENT_DETAILED = 'LOAN_PAYMENTS_CREDIT_CARD_PAYMENT'

# Income needs positive evidence: Plaid's INCOME primary category (wages,
# interest, dividends, ...). See _is_income for why this is stricter than the
# expense side's transfer rule.
_INCOME_PREFIX = 'INCOME'

_CENTS = Decimal('0.01')


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


def _percentile(values, q):
    """Linear-interpolation percentile of a non-empty list; Decimal preserving."""
    ordered = sorted(values)
    pos = q * (len(ordered) - 1)
    lower = int(pos)
    if lower + 1 >= len(ordered):
        return ordered[-1]
    return ordered[lower] + (ordered[lower + 1] - ordered[lower]) * (pos - lower)


def _monthly_estimate(txns, cadence, inflow=False, percentile=ESTIMATE_PERCENTILE):
    """Monthly-equivalent amount of a stream, at the given percentile.

    One occurrence per date (the unit _build_stream counts cadence in), its
    amount the sum of that date's charges — or, for an inflow, the absolute sum
    of that date's deposits; rows of the other sign (refunds on a bill, a
    clawback on a paycheck) are ignored. Only occurrences in the
    ESTIMATE_WINDOW_DAYS ending at the stream's latest occurrence count
    (exclusive of the far end, so a monthly stream has 12, not 13) — anchored on
    the stream rather than on today, so a quarterly stream always has its recent
    history. With one or two occurrences the percentile is simply the best
    available.
    """
    by_date = defaultdict(Decimal)
    for t in txns:
        if inflow and t.amount < 0:
            by_date[t.date] -= t.amount
        elif not inflow and t.amount > 0:
            by_date[t.date] += t.amount
    if not by_date:
        return Decimal('0.00')
    cutoff = max(by_date) - timedelta(days=ESTIMATE_WINDOW_DAYS)
    recent = [amount for d, amount in by_date.items() if d > cutoff]
    typical = _percentile(recent, percentile)
    return (typical * MONTHLY_FACTOR[cadence]).quantize(_CENTS, rounding=ROUND_HALF_UP)


def _is_transfer(txns):
    """True when most of a stream's categorized rows are card payments or transfers.

    Rows with no category at all abstain rather than vote "not a transfer": the
    category columns arrived in a later migration, so a long-running autopay
    stream can be mostly uncategorized history, and letting that history outvote
    its categorized rows would count a card payment as a bill. A stream with no
    categorized rows is not a transfer — the same stance spending.is_spend takes.
    """
    categorized = [t for t in txns if t.category or t.category_detailed]
    hits = sum(
        1 for t in categorized
        if (t.category or '').upper().startswith(_TRANSFER_PREFIX)
        or (t.category_detailed or '').upper() == _CARD_PAYMENT_DETAILED
    )
    return hits * 2 > len(categorized)


def _is_income(txns):
    """True when most of a stream's categorized rows carry an INCOME category.

    Deliberately stricter than _is_transfer. A mistake on the expense side
    over-counts a bill, which errs safe; a mistake here overstates what comes in
    and so what is left over, which does not. So income needs positive evidence:
    uncategorized rows abstain, and a stream with no categorized rows at all is
    not income. Transfers in, card-payment credits, refunds and reimbursements
    all fail this test and are listed as "not income".
    """
    categorized = [t for t in txns if t.category or t.category_detailed]
    hits = sum(
        1 for t in categorized
        if (t.category or '').upper().startswith(_INCOME_PREFIX)
    )
    return hits * 2 > len(categorized) > 0


def _income_excluded_reason(stream, txns):
    """Why an income stream is left out of the monthly income total, or None."""
    if not stream['active']:
        return 'inactive'
    if stream['cadence'] not in _TOTAL_CADENCES:
        return 'annual'
    if not _is_income(txns):
        return 'not income'
    return None


def _excluded_reason(stream, txns):
    """Why a bill is left out of the fixed monthly total, or None if counted."""
    if not stream['active']:
        return 'inactive'
    if stream['cadence'] not in _TOTAL_CADENCES:
        return 'annual'
    if _is_transfer(txns):
        return 'transfer'
    return None


def fixed_monthly_total(bills):
    """(total, count) over the bills counted toward the fixed monthly total.

    Sums the already-rounded per-bill figures, so the total equals the sum of
    the rows the page displays.
    """
    counted = [b for b in bills if b['excluded_reason'] is None]
    return sum((b['monthly_amount'] for b in counted), Decimal('0.00')), len(counted)


def monthly_income_total(income):
    """(total, count) over the income streams counted toward monthly income.

    Same shape as fixed_monthly_total: sums the rounded per-stream figures.
    """
    return fixed_monthly_total(income)


def detect_bills(transactions, today):
    """Detect recurring outflow streams and compute monthly payment status.

    Returns a list of bill dicts (same shape as detect_subscriptions streams,
    plus 'payment_status', 'expected_date_this_month', 'monthly_amount' and
    'excluded_reason'), sorted unpaid-first,
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
    bills, _income = detect_recurring_from_groups(groups, today)
    return bills


def detect_recurring_from_groups(groups, today):
    """(bills, income) from already-grouped transactions, in one pass.

    Each group's stream is built once: an outflow becomes a bill (payment
    status, monthly estimate at P75, excluded reason), an inflow becomes an
    income stream (monthly estimate at P25, excluded reason). Bills are sorted
    unpaid-first, then upcoming, then paid, then inactive; within each group by
    amount magnitude descending. Income is sorted counted-first, then by
    monthly amount descending.
    """
    bills = []
    income = []
    for group in groups:
        stream = _build_stream(group, today)
        if stream is None:
            continue
        if stream['is_inflow']:
            stream['monthly_amount'] = _monthly_estimate(
                group, stream['cadence'], inflow=True, percentile=INCOME_PERCENTILE,
            )
            stream['excluded_reason'] = _income_excluded_reason(stream, group)
            income.append(stream)
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
        stream['monthly_amount'] = _monthly_estimate(group, stream['cadence'])
        stream['excluded_reason'] = _excluded_reason(stream, group)
        bills.append(stream)

    bills.sort(key=lambda b: (_STATUS_ORDER[b['payment_status']], -abs(b['amount'])))
    income.sort(key=lambda s: (s['excluded_reason'] is not None, -s['monthly_amount']))
    return bills, income
