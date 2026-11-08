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
import re
from collections import Counter, defaultdict
from dataclasses import dataclass, field
from datetime import date, timedelta
from decimal import ROUND_HALF_UP, Decimal

from app.recurring_rules import apply_rules, pattern_hint
from app.subscriptions import (
    _MONTHLY_NOMINAL,
    _build_stream,
    _display_name,
    _group_transactions,
    _median,
    grouping_key,
    merge_by_descriptor,
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

# A Zelle payment sends money to another person — rent, a tutor, a therapist —
# yet Plaid files it under TRANSFER_OUT alongside moves between the user's own
# accounts, and its detailed category does not tell the two apart. The raw
# descriptor does, so an outflow row naming Zelle is a payment, not a transfer.
_P2P_PAYMENT_RE = re.compile(r'\bZELLE\b', re.IGNORECASE)

# Income needs positive evidence: Plaid's INCOME primary category (wages,
# interest, dividends, ...). See _is_income for why this is stricter than the
# expense side's transfer rule.
_INCOME_PREFIX = 'INCOME'

_CENTS = Decimal('0.01')

# Same-amount sub-streams: a merchant group not detected as a whole is split by
# exact amount, and a subset counts only as an active monthly stream. Other
# cadences proved to be coincidences: many bins per group give each its own
# chance to pass at MIN_OCCURRENCES (knowledge 003's amendment). The one
# exception to MIN_OCCURRENCES is a new monthly pair — two charges at one exact
# amount in consecutive months (subscriptions._is_new_monthly_pair) — accepted
# so a new bill counts from its second charge; it is badged "new", and it
# lapses by the ordinary `active` rule if no third charge follows.
SPLIT_CADENCES = {'monthly'}

# "Possibly recurring": a merchant with no stream, charged in at least
# SUGGEST_MIN_MONTHS of the SUGGEST_WINDOW_MONTHS complete months before this
# one, on charge days a median of SUGGEST_MIN_MEDIAN_GAP_DAYS or more apart
# (everyday merchants are charged every few days).
SUGGEST_WINDOW_MONTHS = 6
SUGGEST_MIN_MONTHS = 4
SUGGEST_MIN_MEDIAN_GAP_DAYS = 6


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


def _monthly_estimate(txns, cadence, inflow=False, percentile=ESTIMATE_PERCENTILE,
                      by_month=False):
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

    `by_month` is for a stream a user rule forced to monthly: its payments are
    irregular and may come more than once a month, so the estimate is the larger
    of the per-date figure and the same percentile of its calendar-month totals
    in the window — never below one payment, never one part of a split payment.
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
    if by_month:
        months = defaultdict(Decimal)
        for d, amount in by_date.items():
            if d > cutoff:
                months[(d.year, d.month)] += amount
        typical = max(typical, _percentile(list(months.values()), percentile))
    return (typical * MONTHLY_FACTOR[cadence]).quantize(_CENTS, rounding=ROUND_HALF_UP)


def _is_p2p_payment(txn):
    """An outflow row whose raw descriptor names a person-to-person rail."""
    return txn.amount > 0 and bool(_P2P_PAYMENT_RE.search(txn.description or ''))


def _is_transfer(txns):
    """True when most of a stream's categorized rows are card payments or transfers.

    A categorized Zelle outflow (_is_p2p_payment) votes "not a transfer": it
    pays a person. Each row votes on its own, so a mixed group is judged by
    its majority.

    Rows with no category at all abstain rather than vote "not a transfer": the
    category columns arrived in a later migration, so a long-running autopay
    stream can be mostly uncategorized history, and letting that history outvote
    its categorized rows would count a card payment as a bill. A stream with no
    categorized rows is not a transfer — the same stance spending.is_spend takes.
    """
    categorized = [t for t in txns if t.category or t.category_detailed]
    hits = sum(
        1 for t in categorized
        if not _is_p2p_payment(t)
        and ((t.category or '').upper().startswith(_TRANSFER_PREFIX)
             or (t.category_detailed or '').upper() == _CARD_PAYMENT_DETAILED)
    )
    return hits * 2 > len(categorized)


def _is_card_payment(txns):
    """True when most of a group's categorized rows are credit-card payments.

    Paying a card settles charges already counted, so such a group is never
    suggested as possibly recurring. Uncategorized rows abstain, as in
    _is_transfer.
    """
    categorized = [t for t in txns if t.category or t.category_detailed]
    hits = sum(
        1 for t in categorized
        if (t.category_detailed or '').upper() == _CARD_PAYMENT_DETAILED
    )
    return hits * 2 > len(categorized) > 0


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


def _income_excluded_reason(stream, txns, override=False):
    """Why an income stream is left out of the monthly income total, or None.

    `override`: the user's rule says this is recurring income, which stands in
    for the INCOME-category evidence (knowledge 2026-11-06's manual override).
    """
    if not stream['active']:
        return 'inactive'
    if stream['cadence'] not in _TOTAL_CADENCES:
        return 'annual'
    if not override and not _is_income(txns):
        return 'not income'
    return None


def _excluded_reason(stream, txns, override=False):
    """Why a bill is left out of the fixed monthly total, or None if counted.

    `override`: the user's rule says this is a recurring bill, so a transfer
    category does not exclude it.
    """
    if not stream['active']:
        return 'inactive'
    if stream['cadence'] not in _TOTAL_CADENCES:
        return 'annual'
    if not override and _is_transfer(txns):
        return 'transfer'
    return None


def fixed_monthly_total(bills):
    """(total, count) over the bills counted toward the fixed monthly total.

    Sums the already-rounded per-bill figures, so the total equals the sum of
    the rows the page displays.
    """
    counted = [b for b in bills if b['excluded_reason'] is None]
    return sum((b['monthly_amount'] for b in counted), Decimal('0.00')), len(counted)


def essential_monthly_total(bills):
    """(total, count) over the counted bills the user marked essential.

    Same arithmetic as fixed_monthly_total — the rounded per-row figures — so
    essential + not essential always equals the headline total. A mark on an
    uncounted bill adds nothing: it is not in the total either.
    """
    return fixed_monthly_total([b for b in bills if b.get('essential')])


def mark_essential(streams, saved_keys):
    """Set each stream's 'essential' from the saved EssentialMark keys: true
    when any of its `essential_keys` is saved."""
    saved = set(saved_keys)
    for stream in streams:
        stream['essential'] = any(k in saved for k in stream['essential_keys'])
    return streams


# EssentialMark.stream_key is String(255); a longer key could never be saved.
ESSENTIAL_KEY_MAX_LENGTH = 255


def _merchant_keys(rows, suffix=''):
    """Essential-mark keys for a detected stream: (keys, primary).

    One `merchant:<grouping key><suffix>` per distinct non-empty grouping key
    among `rows`. A group merged across a Plaid rename carries its old and new
    keys, so a mark made under either name still matches. `primary` — the key
    written when the stream is marked — is the most common one, ties to the
    smallest. (), None when no row has a usable grouping key. A key too long
    to store is left out, so the page never offers a toggle that cannot save.
    """
    limit = ESSENTIAL_KEY_MAX_LENGTH - len('merchant:') - len(suffix)
    counts = Counter(
        k for k in (grouping_key(t) for t in rows) if k and len(k) <= limit
    )
    if not counts:
        return (), None
    top = max(counts.values())
    primary = min(k for k, n in counts.items() if n == top)
    keys = tuple(sorted(f'merchant:{k}{suffix}' for k in counts))
    return keys, f'merchant:{primary}{suffix}'


def _stream_keys(rows):
    """The sorted distinct non-empty grouping keys of `rows`: what a quick
    "Not recurring" button posts to locate its stream again (routes.py)."""
    return tuple(sorted({k for k in (grouping_key(t) for t in rows) if k}))


def _set_rows(stream, rows):
    """Attach the row objects a stream was built from — references, not
    copies — so a quick mark can check that a rule claims exactly them."""
    stream['rows'] = list(rows)
    stream['stream_keys'] = _stream_keys(rows)
    return stream


def _set_keys(stream, keys, primary):
    stream['essential_keys'] = keys
    stream['essential_key'] = primary
    stream['essential'] = False
    return stream


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


_FORCED_MONTHLY = ('monthly', _MONTHLY_NOMINAL)


def _finish_income(stream, txns, override=False):
    stream['monthly_amount'] = _monthly_estimate(
        txns, stream['cadence'], inflow=True, percentile=INCOME_PERCENTILE,
    )
    stream['excluded_reason'] = _income_excluded_reason(stream, txns, override)
    return stream


def _finish_bill(stream, txns, today, override=False):
    if not stream['active']:
        stream['payment_status'] = 'inactive'
        stream['expected_date_this_month'] = _safe_date(
            today.year, today.month, _expected_day_of_month(txns)
        )
    elif stream['cadence_forced']:
        # A rule asserted this irregular stream recurs, so it has no expected
        # day to be late against: paid once anything posted this month,
        # otherwise upcoming — never a false "Unpaid" (knowledge 005).
        expected_date = _safe_date(today.year, today.month, _expected_day_of_month(txns))
        paid = any(t.date.year == today.year and t.date.month == today.month
                   for t in txns)
        stream['payment_status'] = 'paid' if paid else 'upcoming'
        stream['expected_date_this_month'] = expected_date
    else:
        status, expected_date = _payment_status(txns, today)
        stream['payment_status'] = status
        stream['expected_date_this_month'] = expected_date
    stream['monthly_amount'] = _monthly_estimate(
        txns, stream['cadence'], by_month=stream['cadence_forced'],
    )
    stream['excluded_reason'] = _excluded_reason(stream, txns, override)
    return stream


def _rule_entry(claim, status, stream=None):
    """One rule as the "Your rules" card and "Marked not recurring" show it."""
    rule = claim.rule
    return {
        'id': rule.id,
        'label': rule.label,
        'pattern': rule.pattern,
        'direction': rule.direction,
        'amount_min': rule.amount_min,
        'amount_max': rule.amount_max,
        'action': rule.action,
        'rows_won': len(claim.rows),
        'last_matched': claim.rows[-1].date if claim.rows else None,
        'sources': claim.sources,
        'stream_keys': _stream_keys(claim.rows),
        'status': status,
        'stream': stream,
    }


def _split_by_amount(group, today):
    """Same-amount sub-streams of a group that is not a stream as a whole.

    Its outflow rows are binned by exact amount, and each bin goes through
    _build_stream with `pair=True`: two charges at one exact amount about a
    month apart in consecutive months are a new monthly bill (`new` set), below
    MIN_OCCURRENCES. A bin is accepted only as an active monthly stream
    (SPLIT_CADENCES). A bin holding the whole group is skipped — it already
    failed — unless it is such a pair, which whole-group detection never
    accepts. Returns [(amount, stream, row positions)] by amount.
    """
    bins = defaultdict(list)
    for i, t in enumerate(group):
        if t.amount > 0:
            bins[t.amount].append(i)
    accepted = []
    for amount in sorted(bins):
        positions = bins[amount]
        rows = [group[i] for i in positions]
        # Card payments and transfers are never a new bill: before pairs they
        # produced nothing at all, and they would only be listed uncounted.
        stream = _build_stream(rows, today, pair=not _is_transfer(rows))
        if len(positions) == len(group) and not (stream and stream['new']):
            continue
        if stream is None or stream['cadence'] not in SPLIT_CADENCES or not stream['active']:
            continue
        accepted.append((amount, stream, positions))
    return accepted


def _window_months(today):
    """The SUGGEST_WINDOW_MONTHS complete calendar months before today's, oldest first."""
    months = []
    year, month = today.year, today.month
    for _ in range(SUGGEST_WINDOW_MONTHS):
        month -= 1
        if month == 0:
            year, month = year - 1, 12
        months.append((year, month))
    return months[::-1]


def _suggestion(group, remaining, today, has_split):
    """A "Possibly recurring" entry for a group with no stream, or None.

    `remaining` are the group's rows in no accepted sub-stream; only their
    outflows are judged. The transfer badge is judged on the whole group.
    """
    out = [t for t in remaining if t.amount > 0]
    if not out:
        return None
    window = set(_window_months(today))
    in_window = [t for t in out if (t.date.year, t.date.month) in window]
    totals = defaultdict(Decimal)
    for t in in_window:
        totals[(t.date.year, t.date.month)] += t.amount
    if len(totals) < SUGGEST_MIN_MONTHS:
        return None
    days = sorted({t.date for t in in_window})
    gaps = [(b - a).days for a, b in zip(days, days[1:])]
    if not gaps or _median(gaps) < SUGGEST_MIN_MEDIAN_GAP_DAYS:
        return None
    return {
        'name': _display_name(group),
        'months': len(totals),
        'window_months': SUGGEST_WINDOW_MONTHS,
        'typical_month': Decimal(_median(list(totals.values()))).quantize(
            _CENTS, rounding=ROUND_HALF_UP),
        'last_date': max(t.date for t in out),
        'pattern_hint': pattern_hint(out),
        'is_transfer': _is_transfer(group),
        'has_split': has_split,
        'rows': out,
        'stream_keys': _stream_keys(out),
    }


@dataclass
class Recurring:
    bills: list
    income: list
    rules: list     # one _rule_entry per rule, in the order given
    marked: list    # the 'not_recurring' rules that won rows
    suggestions: list = field(default_factory=list)   # "Possibly recurring"; never counted


def detect_recurring_with_rules(groups, today, rules):
    """Bills, income and the user's rules, from already-grouped transactions.

    The rules claim their rows first (app/recurring_rules.py). What is left goes
    through automatic detection exactly as before, merges included. Each rule's
    rows then form one stream of their own, named by its label:

    - 'recurring', outflow → a bill never excluded as a transfer. If no cadence
      is detected it is treated as monthly — the user asserted it recurs — and
      estimated from its monthly totals. It can still be inactive or annual.
    - 'recurring', inflow → counted income without INCOME-category evidence,
      but only with a detected cadence: forcing one would overstate income.
    - 'not_recurring' → the rows leave detection and are listed as marked.

    A leftover group that is no stream as a whole is split by exact amount
    (_split_by_amount); each accepted subset is a bill named with its amount,
    except a new pair holding all of the group's outflows, which is the
    merchant itself and keeps its name and unsuffixed key.
    Groups with no stream as a whole may become "Possibly recurring"
    suggestions (_suggestion), which are never counted.
    """
    result = apply_rules(groups, rules) if rules else None
    leftover = result.groups if result else groups

    bills = []
    income = []
    suggestions = []
    for group in merge_by_descriptor(leftover):
        stream = _build_stream(group, today)
        if stream is None:
            splits = _split_by_amount(group, today)
            outflows = sum(1 for t in group if t.amount > 0)
            taken = set()
            for amount, sub, positions in splits:
                rows = [group[i] for i in positions]
                sub['pattern_hint'] = pattern_hint(rows)
                sub['rule_id'] = None
                _set_rows(sub, rows)
                if sub['new'] and len(positions) == outflows:
                    # A new pair that is the whole group is the merchant
                    # itself: its own name and unsuffixed key, so a mark
                    # survives the third charge that makes it an ordinary
                    # whole-group stream.
                    sub['split_amount'] = None
                    _set_keys(sub, *_merchant_keys(rows))
                else:
                    sub['name'] = f'{_display_name(group)} · ${amount:,.2f}'
                    sub['split_amount'] = amount
                    # Suffixed with the plan's amount, and without the parent
                    # key, so marking one plan never marks another at the
                    # same merchant.
                    _set_keys(sub, *_merchant_keys(rows, suffix=f'@{amount:.2f}'))
                bills.append(_finish_bill(sub, rows, today))
                taken.update(positions)
            if not _is_card_payment(group):
                remaining = [t for i, t in enumerate(group) if i not in taken]
                entry = _suggestion(group, remaining, today, has_split=bool(splits))
                if entry:
                    suggestions.append(entry)
            continue
        stream['pattern_hint'] = pattern_hint(group)
        stream['split_amount'] = None
        stream['rule_id'] = None
        _set_rows(stream, group)
        if stream['is_inflow']:
            # Income is never marked essential: it is not an expense.
            _set_keys(stream, (), None)
            income.append(_finish_income(stream, group))
        else:
            _set_keys(stream, *_merchant_keys(group))
            bills.append(_finish_bill(stream, group, today))

    entries = []
    marked = []
    for claim in (result.claims if result else []):
        rule = claim.rule
        if not claim.rows:
            entries.append(_rule_entry(claim, '0 rows'))
            continue
        if rule.action == 'not_recurring':
            entry = _rule_entry(claim, 'marked not recurring')
            entries.append(entry)
            marked.append(entry)
            continue
        inflow = rule.direction == 'inflow'
        stream = _build_stream(
            claim.rows, today, fallback_cadence=None if inflow else _FORCED_MONTHLY,
        )
        if stream is None:
            entries.append(_rule_entry(claim, 'no regular cadence'))
            continue
        stream['name'] = rule.label
        stream['pattern_hint'] = rule.pattern
        stream['split_amount'] = None
        stream['rule_id'] = rule.id
        # A rule stream is changed by deleting its rule, never quick-marked.
        stream['rows'] = list(claim.rows)
        stream['stream_keys'] = ()
        key = None if inflow else f'rule:{rule.id}'
        _set_keys(stream, (key,) if key else (), key)
        if inflow:
            income.append(_finish_income(stream, claim.rows, override=True))
        else:
            bills.append(_finish_bill(stream, claim.rows, today, override=True))
        reason = stream['excluded_reason']
        entries.append(_rule_entry(
            claim, 'counted' if reason is None else f'not counted: {reason}', stream,
        ))

    bills.sort(key=lambda b: (_STATUS_ORDER[b['payment_status']], -abs(b['amount'])))
    income.sort(key=lambda s: (s['excluded_reason'] is not None, -s['monthly_amount']))
    marked.sort(key=lambda m: (m['label'].lower(), m['id'] or 0))
    suggestions.sort(key=lambda s: (s['is_transfer'], -s['typical_month'], s['name'].lower()))
    return Recurring(bills=bills, income=income, rules=entries, marked=marked,
                     suggestions=suggestions)


def detect_recurring_from_groups(groups, today):
    """(bills, income) from already-grouped transactions, in one pass.

    Each group's stream is built once: an outflow becomes a bill (payment
    status, monthly estimate at P75, excluded reason), an inflow becomes an
    income stream (monthly estimate at P25, excluded reason). Bills are sorted
    unpaid-first, then upcoming, then paid, then inactive; within each group by
    amount magnitude descending. Income is sorted counted-first, then by
    monthly amount descending. Groups that are one merchant renamed by Plaid
    are merged first (`merge_by_descriptor`). No user rules — see
    detect_recurring_with_rules.
    """
    found = detect_recurring_with_rules(groups, today, [])
    return found.bills, found.income
