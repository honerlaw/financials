"""Recurring-transaction (subscription) detection.

Pure functions over Transaction rows — no DB access, no schema changes.
Detection is computed live on page load; at personal-finance volumes a
single pass over the transactions table is plenty fast.

Cadence regularity is the only detection gate. Amount consistency never
gates a stream (card payments and utilities vary wildly month to month);
a wide amount spread just sets `varies` for display.
"""

import re
from collections import Counter, defaultdict
from datetime import timedelta
from difflib import SequenceMatcher

# (name, nominal gap in days, tolerance) — buckets are disjoint by design.
CADENCES = [
    ('weekly', 7, 2),
    ('biweekly', 14, 3),
    ('monthly', 30, 6),
    ('quarterly', 91, 12),
    ('annual', 365, 30),
]

MIN_OCCURRENCES = 3          # charges needed to call a stream recurring
MIN_OCCURRENCES_ANNUAL = 2   # annual streams rarely have 3 years of history
GAP_REGULARITY = 0.7         # fraction of gaps that must sit inside the bucket
INACTIVE_MULTIPLIER = 1.5    # overdue by > 1.5x cadence -> inactive
VARIES_THRESHOLD = 0.25      # amount MAD > 25% of median -> "varies" badge
FUZZY_THRESHOLD = 0.82       # SequenceMatcher ratio to collapse merchant keys

# Bump whenever normalize_merchant, _similar, or FUZZY_THRESHOLD changes shape.
# app/merchant_groups.py compares this against the stored algo_version and does
# exactly one full rebuild on a mismatch, so a tuned dial can never leave a
# silently stale index behind.
GROUPING_ALGO_VERSION = 1

# Tokens that carry no merchant identity ("NETFLIX.COM" vs "Netflix").
_NOISE_TOKENS = {'com', 'net', 'org', 'www', 'inc', 'llc', 'ltd', 'corp', 'the'}


def normalize_merchant(text):
    """Lowercase, strip digits/punctuation/noise tokens.

    "NETFLIX.COM 866-579-7172" and "Netflix" both normalize to "netflix".
    """
    text = re.sub(r'[^a-z]+', ' ', text.lower())
    return ' '.join(t for t in text.split() if t not in _NOISE_TOKENS)


def grouping_key(txn):
    """The key `txn` groups by — the one definition both the live and the
    indexed path use.

    Plaid's merchant_entity_id, when present, is a stronger identity than any
    string comparison, so it wins outright and is namespaced to keep it from
    ever colliding with a normalized name. Otherwise fall back to the fuzzy-
    matchable normalized name. Returns '' when neither yields anything, which
    callers treat as ungroupable.
    """
    if txn.merchant_entity_id:
        return 'entity:%s' % txn.merchant_entity_id
    return normalize_merchant(txn.merchant_name or txn.description)


def _similar(a, b, matcher=None):
    """Fuzzy match between two normalized merchant keys.

    The bounds before the ratio() call are pure optimization — they reject only
    pairs that provably cannot reach FUZZY_THRESHOLD, so the predicate is
    identical to a bare SequenceMatcher.ratio() comparison. They matter because
    grouping calls this O(keys x groups) times: difflib's own ratio() is the
    single most expensive thing either page does.

    Pass `matcher` (a SequenceMatcher with seq2 already set to `b`) to reuse the
    b-side chain across a whole scan instead of rebuilding it per pair.
    """
    if a == b:
        return True
    if len(a) >= 5 and len(b) >= 5 and (a.startswith(b) or b.startswith(a)):
        return True
    # ratio() = 2*M/T is bounded above by 2*min(len)/(len(a)+len(b)); when that
    # ceiling is under the threshold no amount of matching can reach it.
    if 2.0 * min(len(a), len(b)) / (len(a) + len(b)) < FUZZY_THRESHOLD:
        return False
    if matcher is None:
        matcher = SequenceMatcher(None, '', b, autojunk=False)
    matcher.set_seq1(a)
    # difflib's own cheap upper bounds, cheapest first.
    if matcher.real_quick_ratio() < FUZZY_THRESHOLD:
        return False
    if matcher.quick_ratio() < FUZZY_THRESHOLD:
        return False
    return matcher.ratio() >= FUZZY_THRESHOLD


def _median(values):
    """Median of a non-empty list; preserves Decimal arithmetic."""
    ordered = sorted(values)
    n = len(ordered)
    mid = n // 2
    if n % 2:
        return ordered[mid]
    return (ordered[mid - 1] + ordered[mid]) / 2


def _display_name(txns):
    """Most common merchant_name, falling back to description."""
    names = Counter(t.merchant_name for t in txns if t.merchant_name)
    if names:
        return names.most_common(1)[0][0]
    return Counter(t.description for t in txns).most_common(1)[0][0]


def _group_key(txns):
    """Representative normalized name for a group of transactions."""
    keys = Counter(
        normalize_merchant(t.merchant_name or t.description) for t in txns
    )
    return keys.most_common(1)[0][0]


def _group_transactions(txns):
    """Group by merchant_entity_id when present, else fuzzy-collapsed
    normalized merchant name. Grouping is global across accounts and
    institutions so a card switch doesn't split a stream.
    """
    by_entity = defaultdict(list)
    by_name = defaultdict(list)
    for t in txns:
        if t.merchant_entity_id:
            by_entity[t.merchant_entity_id].append(t)
        else:
            key = normalize_merchant(t.merchant_name or t.description)
            if key:
                by_name[key].append(t)

    # Entity-id groups seed the canonical list; name groups then merge into
    # the first canonical group whose key fuzzy-matches (sorted for
    # determinism), or start their own.
    groups = [[_group_key(ts), ts] for _, ts in sorted(by_entity.items())]
    for key in sorted(by_name):
        # One matcher per key, seq2 pinned: difflib caches the b-side chain, so
        # scanning it across every group costs one build instead of one per pair.
        matcher = SequenceMatcher(None, '', key, autojunk=False)
        for group in groups:
            if _similar(group[0], key, matcher):
                group[1].extend(by_name[key])
                break
        else:
            groups.append([key, by_name[key]])
    return [ts for _, ts in groups]


def _classify_cadence(gaps, occurrences):
    """Map the median inter-charge gap to a cadence bucket, requiring most
    gaps to be regular. Returns (name, nominal_days) or None.
    """
    if not gaps:
        return None
    med = _median(gaps)
    for name, nominal, tol in CADENCES:
        if abs(med - nominal) > tol:
            continue
        required = MIN_OCCURRENCES_ANNUAL if name == 'annual' else MIN_OCCURRENCES
        if occurrences < required:
            return None
        within = sum(1 for g in gaps if abs(g - nominal) <= tol)
        if within / len(gaps) >= GAP_REGULARITY:
            return name, nominal
        return None  # median fit the bucket but the gaps are irregular
    return None


def _build_stream(txns, today):
    """Build a stream dict from one merchant group, or None if the group
    isn't recurring."""
    dates = sorted({t.date for t in txns})  # same-day charges = one occurrence
    gaps = [(b - a).days for a, b in zip(dates, dates[1:])]
    cadence = _classify_cadence(gaps, len(dates))
    if cadence is None:
        return None
    cadence_name, nominal = cadence

    amounts = [t.amount for t in txns]
    median_amount = _median(amounts)
    mad = _median([abs(a - median_amount) for a in amounts])
    varies = bool(median_amount) and mad / abs(median_amount) > VARIES_THRESHOLD

    last_date = dates[-1]
    return {
        'name': _display_name(txns),
        'cadence': cadence_name,
        'cadence_days': nominal,
        'amount': median_amount,
        'varies': varies,
        'is_inflow': median_amount < 0,
        'last_date': last_date,
        'next_date': last_date + timedelta(days=nominal),
        'count': len(txns),
        'active': (today - last_date).days <= INACTIVE_MULTIPLIER * nominal,
        'account_keys': sorted({(t.institution_id, t.account_id) for t in txns}),
    }


def detect_subscriptions(transactions, today):
    """Detect recurring streams across all (non-removed) transactions.

    Everything recurring qualifies — card payments, transfers, utilities,
    and inflows (paychecks) included; no category exclusions. Pending
    transactions count: they're real charges, and excluding them would
    falsely mark fresh streams inactive.

    Returns stream dicts sorted active-first, then by amount magnitude.
    """
    # The removed-gate lives here (tested contract) even though the route
    # also filters in SQL — callers may pass unfiltered rows.
    live = [t for t in transactions if not t.removed]
    return detect_subscriptions_from_groups(_group_transactions(live), today)


def detect_subscriptions_from_groups(groups, today):
    """Build streams from already-grouped transactions.

    Split out so the persisted merchant-group index can supply the grouping
    (see app/merchant_groups.py) without re-deriving it. Everything here is
    cheap and date-dependent — `active` and `next_date` are computed from
    `today` on every call and are deliberately never cached, so a stored index
    cannot go stale merely because the calendar advanced.

    `groups` is an iterable of transaction lists; each list is one merchant.
    """
    streams = []
    for group in groups:
        stream = _build_stream(group, today)
        if stream is not None:
            streams.append(stream)
    streams.sort(key=lambda s: (not s['active'], -abs(s['amount'])))
    return streams
