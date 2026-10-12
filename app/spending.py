"""Dashboard spend aggregation and weekly-budget tracking.

Pure functions computing (a) a daily spend series for the dashboard chart,
(b) a per-week running total against a fixed weekly budget, and (c) the
daily digest's aggregates — the running week, the completed weeks behind it,
and one day's purchases (``day_spend``). Like bills.py and
subscriptions.py these take the reference date as a parameter rather than
calling date.today() internally, so tests stay deterministic
(see .minerva/knowledge: seed-relative-dates-in-time-sensitive-tests).

Spend semantics
---------------
"Spend" is a positive ``amount`` (money leaving the account; negatives are
inflows such as paychecks and refunds) EXCLUDING Plaid transfer and
loan-payment categories — otherwise a credit-card payment (an outflow from
checking) double-counts against the same purchases it settles, and account
transfers inflate the number. ``category`` holds the Plaid
personal_finance_category *primary* (e.g. TRANSFER_OUT, LOAN_PAYMENTS).

Known limitation: ``category`` is nullable and was added by a later migration,
so a transaction with no category (older data, or low Plaid confidence) cannot
be classified and is COUNTED as spend — historical transfers/card-payments may
therefore inflate spend. The exclusion set is provisional, mirroring
subscriptions.py's category stance. (app/chat/tools.py has its own, separate
spend-like aggregation for the LLM tool path; this definition is intentionally
independent.)
"""

from datetime import date, timedelta
from decimal import Decimal
from typing import NamedTuple

WEEKLY_BUDGET = Decimal('1000')

# A purchase strictly above this is itemised by the daily digest.
LARGE_PURCHASE = Decimal('100')

# Plaid personal_finance_category primaries excluded from spend. Prefix-matched
# so detailed variants (TRANSFER_IN/TRANSFER_OUT) are covered by one entry.
_EXCLUDED_SPEND_PREFIXES = ('TRANSFER', 'LOAN_PAYMENTS')


def is_spend(txn):
    """True if ``txn`` is a spending outflow that counts toward the budget."""
    if txn.amount <= 0:
        return False
    category = (txn.category or '').upper()
    return not category.startswith(_EXCLUDED_SPEND_PREFIXES)


def week_start(d):
    """The Sunday starting the week containing ``d`` (weeks run Sun–Sat)."""
    return d - timedelta(days=(d.weekday() + 1) % 7)


def week_label(ws):
    """Short 'Mon D–D' / 'Mon D – Mon D' label for a Sun-start week.

    Public because the daily digest labels its week rows with it too, so a week
    is named the same way in the SMS and in the dashboard's weekly tracker.
    (``routes._week_label`` is a separate, year-carrying variant for the
    transactions table.)
    """
    we = ws + timedelta(days=6)
    if ws.month != we.month:
        return f"{ws.strftime('%b %-d')} – {we.strftime('%b %-d')}"
    return f"{ws.strftime('%b %-d')}–{we.day}"


def daily_spend(transactions, start, end_exclusive):
    """Ordered ``[(date, total_spend)]`` for every day in ``[start, end)``.

    Days with no spend are included with a ``Decimal('0')`` total so the chart
    renders an unbroken axis.
    """
    totals = {}
    for txn in transactions:
        if not is_spend(txn):
            continue
        if start <= txn.date < end_exclusive:
            totals[txn.date] = totals.get(txn.date, Decimal('0')) + txn.amount

    series = []
    day = start
    while day < end_exclusive:
        series.append((day, totals.get(day, Decimal('0'))))
        day += timedelta(days=1)
    return series


def week_spend(transactions, today):
    """Total ``is_spend`` amount for the Sun–Sat week containing ``today``.

    Used by the budget-alert notifier for the current week's household spend.
    The caller passes an already-fetched transaction list; this re-filters to
    the week defensively so a padded fetch can't inflate the total. Takes
    ``today`` as a parameter for deterministic tests, like the rest of this
    module.
    """
    ws = week_start(today)
    week_end_exclusive = ws + timedelta(days=7)
    total = Decimal('0')
    for txn in transactions:
        if is_spend(txn) and ws <= txn.date < week_end_exclusive:
            total += txn.amount
    return total


def purchase_date(txn):
    """The day a purchase was made: ``authorized_date``, else ``date``.

    For a POSTED transaction Plaid's ``date`` is the posting date, which can
    trail the purchase by days. Keying a per-day report on it would show a
    purchase once while pending (under its purchase day) and again once posted
    (under its posting day). Week totals deliberately stay on ``date``; only
    the digest's Yesterday section keys on this. ``getattr`` so a
    transaction-like object without the field falls back to ``date``.
    """
    return getattr(txn, 'authorized_date', None) or txn.date


class DaySpend(NamedTuple):
    """One day's purchases, as ``day_spend`` aggregates them.

    ``day`` is the date aggregated, carried so a caller printing it cannot
    disagree with the numbers. ``large`` is ``[(label, amount)]`` for every purchase over
    ``LARGE_PURCHASE``, largest first. ``by_category`` is ``[(category,
    total)]``, largest first, where ``category`` is the Plaid primary as stored
    (upper-cased) or ``None`` when the row has none.
    """
    day: date
    count: int
    total: Decimal
    large: list
    by_category: list


def day_spend(transactions, day, large_over=LARGE_PURCHASE):
    """Aggregate the ``is_spend`` transactions purchased on ``day`` — pure.

    The same spend definition the budget line and weekly history use, keyed on
    ``purchase_date`` rather than ``date``, so a purchase is reported under the
    day it was made and is not reported again when its pending row is replaced
    by the posted one (provided Plaid gives both the same ``authorized_date``).
    Every row counted here is still in some week total the digest prints,
    though possibly a different week than ``day`` falls in. Filters the input
    defensively, like every aggregate here, so a caller may pass a wider fetch.
    Ties sort by label / category name so the output is stable.
    """
    count = 0
    total = Decimal('0')
    large = []
    categories = {}
    for txn in transactions:
        if purchase_date(txn) != day or not is_spend(txn):
            continue
        count += 1
        total += txn.amount
        if txn.amount > large_over:
            large.append((txn.merchant_name or txn.description, txn.amount))
        key = (txn.category or '').upper() or None
        categories[key] = categories.get(key, Decimal('0')) + txn.amount
    large.sort(key=lambda item: (-item[1], item[0]))
    by_category = sorted(categories.items(),
                         key=lambda item: (-item[1], item[0] or ''))
    return DaySpend(day, count, total, large, by_category)


def recent_week_spend(transactions, today, weeks=4):
    """``[(week_start, total)]`` for the ``weeks`` COMPLETE weeks before ``today``'s.

    Oldest first. The week containing ``today`` is excluded — it is still
    running, and the digest reports it separately as the budget line; a partial
    week sitting in a column of finished ones reads as a drop that is not real.

    A week with no spend is emitted with ``Decimal('0')`` rather than skipped,
    the same way ``daily_spend`` emits empty days, so the caller always gets
    exactly ``weeks`` entries and a quiet week is visible as a quiet week.
    Filters the input defensively, so a caller may pass a wider fetch.
    """
    current = week_start(today)
    first = current - timedelta(days=7 * weeks)

    totals = {}
    for txn in transactions:
        if not is_spend(txn):
            continue
        if first <= txn.date < current:
            ws = week_start(txn.date)
            totals[ws] = totals.get(ws, Decimal('0')) + txn.amount

    series = []
    ws = first
    while ws < current:
        series.append((ws, totals.get(ws, Decimal('0'))))
        ws += timedelta(days=7)
    return series


def weekly_budget(transactions, month_start, month_end_exclusive, today,
                  budget=WEEKLY_BUDGET):
    """Per-week spend vs ``budget`` for the Sun–Sat weeks overlapping the month.

    Each returned dict covers a FULL Sun–Sat week (``spent`` sums the whole
    week, including days that fall outside the month), so an edge week that
    straddles the month boundary is compared against the weekly budget fairly
    rather than undercounted. ``is_current`` is True only for the week
    containing ``today`` and only when that week overlaps the displayed month.

    Returns dicts with: ``week_start``, ``week_end`` (Saturday), ``label``,
    ``spent``, ``budget``, ``remaining`` (may be negative), ``pct`` (0..100+,
    int), ``over`` (bool), ``is_current`` (bool).
    """
    first_week = week_start(month_start)
    # Last day of the month is the day before the exclusive end.
    last_week = week_start(month_end_exclusive - timedelta(days=1))
    current_week = week_start(today)

    # Sum spend per Sun-start week across the full padded span in one pass.
    spent_by_week = {}
    span_end = last_week + timedelta(days=7)
    for txn in transactions:
        if not is_spend(txn):
            continue
        if first_week <= txn.date < span_end:
            ws = week_start(txn.date)
            spent_by_week[ws] = spent_by_week.get(ws, Decimal('0')) + txn.amount

    weeks = []
    ws = first_week
    while ws <= last_week:
        spent = spent_by_week.get(ws, Decimal('0'))
        remaining = budget - spent
        pct = int(spent / budget * 100) if budget else 0
        weeks.append({
            'week_start': ws,
            'week_end': ws + timedelta(days=6),
            'label': week_label(ws),
            'spent': spent,
            'budget': budget,
            'remaining': remaining,
            'pct': pct,
            'over': spent > budget,
            'is_current': ws == current_week,
        })
        ws += timedelta(days=7)
    return weeks
