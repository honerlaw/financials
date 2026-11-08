"""Recurring-transaction (subscription) detection.

Pure functions over transaction-like rows — no DB access, no schema changes.
In production the rows are plain result rows carrying only the columns listed
in app/merchant_groups.py's _DETECTION_COLUMNS, not ORM instances: reading any
other attribute here (or in app/bills.py) needs a column added there.
Detection is computed live on page load; at personal-finance volumes a
single pass over the transactions table is plenty fast.

Cadence regularity is the only detection gate. Amount consistency never
gates a stream (card payments and utilities vary wildly month to month);
a wide amount spread just sets `varies` for display.

Grouping has two signals. The first is the merchant key (Plaid's entity id,
else the fuzzy-matched merchant name), persisted by app/merchant_groups.py.
The second, `merge_by_descriptor`, runs on every request after the groups are
read: groups that share a transaction name (Plaid's `name`, our `description`
— for card issuers the network descriptor, which stays put when Plaid's
merchant-name enrichment changes) are merged when that looks like a rename.
The persisted index keeps the pre-merge grouping.
"""

import re
from collections import Counter, defaultdict
from datetime import timedelta
from difflib import SequenceMatcher

# (name, nominal gap in days, tolerance) — buckets are disjoint by design: the
# median gap picks at most one. (Weekly's skipped-session gaps, used only for
# its regularity test, overlap the biweekly band.)
CADENCES = [
    ('weekly', 7, 2),
    ('biweekly', 14, 3),
    ('monthly', 30, 6),
    ('quarterly', 91, 12),
    ('annual', 365, 30),
]

# A monthly bill paid by hand posts on a day that drifts from month to month, so
# its gaps swing well outside 30 ± 6 even though it is paid exactly once per
# calendar month. Inside the monthly bucket only, a gap between two consecutive
# calendar months also counts as regular when it is within this many days of
# 30 (15–45, inclusive). Bucket selection by median gap is unchanged.
_MONTHLY_NOMINAL = 30
MONTHLY_CALENDAR_SLACK = 15

# A weekly appointment skips a session now and then (holidays, sick weeks), so
# its gaps include two and three weeks. Inside the weekly bucket only, a gap
# within the bucket's tolerance of one of these multiples of 7 also counts as
# regular, and a weekly stream stays active until it is overdue past the
# largest such gap. Bucket selection by median gap is unchanged, so a stream
# whose median gap is 14 days is still biweekly.
#
# Those bands (5-9, 12-16, 19-23 days) cover most gaps a frequent merchant
# shows, so on their own they let about a quarter of cafes and fuel stations
# with gaps of 3-14 days pass as weekly. An appointment keeps its weekday; a
# habit does not. So the skip allowance is used only when the plain 7 ± 2 test
# fails and at least WEEKLY_SKIP_MIN_WEEKDAY_SHARE of the stream's charge days
# fall on its most common weekday (Plaid's posting date can slip a day, hence
# well under 1). In simulation, this brings random 3-14-day merchants with a
# dozen gaps back to about 4%, close to the old 2%.
_WEEKLY_NOMINAL = 7
WEEKLY_SKIP_MULTIPLES = (2, 3)
WEEKLY_SKIP_MIN_WEEKDAY_SHARE = 0.4

_WEEKLY_BUCKET = CADENCES[0]
_MONTHLY_BUCKET = CADENCES[2]
assert _WEEKLY_BUCKET[0] == 'weekly' and _MONTHLY_BUCKET[0] == 'monthly'

MIN_OCCURRENCES = 3          # charges needed to call a stream recurring (except a new pair, _is_new_monthly_pair)
MIN_OCCURRENCES_ANNUAL = 2   # annual streams rarely have 3 years of history
GAP_REGULARITY = 0.7         # fraction of gaps that must be regular (_gap_is_regular)
INACTIVE_MULTIPLIER = 1.5    # overdue by > 1.5x cadence -> inactive
VARIES_THRESHOLD = 0.25      # amount MAD > 25% of median -> "varies" badge
FUZZY_THRESHOLD = 0.82       # SequenceMatcher ratio to collapse merchant keys

# Bump whenever normalize_merchant, _similar, FUZZY_THRESHOLD or the grouping
# rule itself (e.g. the member-prefix join) changes shape.
# app/merchant_groups.py compares this against the stored algo_version and does
# exactly one full rebuild on a mismatch, so a tuned dial can never leave a
# silently stale index behind. 2: member-key word-prefix join.
GROUPING_ALGO_VERSION = 2

# A member key's word prefix must be at least this long (spaces counted) to
# join a key to its group. Deliberately aligned with _similar's prefix minimum
# and DESCRIPTOR_MIN_LENGTH.
MEMBER_PREFIX_MIN_LENGTH = 5

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


def is_member(key, representative):
    """Whether a name key assigned to a group may pull its word-extensions in.

    Never the representative itself (_similar's prefix branch already covers
    it), nor a prefix of it: a bare "amazon" that joined an "amazon prime"
    group by reverse prefix must not become a hub for every "amazon ..." key.
    """
    return not representative.startswith(key)


def member_prefix_match(key, members):
    """The group a name key joins through a member key, or None.

    `members` maps member key -> group handle (a group list in memory, a group
    id in the index). The key's word prefixes are tried longest first, and the
    first one that is a member and at least MEMBER_PREFIX_MIN_LENGTH long wins:
    "in acme widgets anytown usa" joins the group holding "in acme widgets".
    Word boundaries only, so "acme widget" never pulls in "acme widgetry".
    Used by both grouping paths, so the rule cannot drift between them.
    """
    tokens = key.split()
    for n in range(len(tokens) - 1, 0, -1):
        prefix = ' '.join(tokens[:n])
        if len(prefix) < MEMBER_PREFIX_MIN_LENGTH:
            return None     # shorter prefixes only get shorter
        if prefix in members:
            return members[prefix]
    return None


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

    A name key that matches no group's representative may still join a group
    through one of its member keys (member_prefix_match): the card network
    appending a city to a descriptor whose plain form already joined.
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
    # determinism), else into the group of a member key that is a word prefix
    # of theirs, or start their own. Sorted order puts a prefix before its
    # extensions, so the member is always seen first.
    groups = [[_group_key(ts), ts] for _, ts in sorted(by_entity.items())]
    members = {}
    for key in sorted(by_name):
        # One matcher per key, seq2 pinned: difflib caches the b-side chain, so
        # scanning it across every group costs one build instead of one per pair.
        matcher = SequenceMatcher(None, '', key, autojunk=False)
        for group in groups:
            if _similar(group[0], key, matcher):
                target = group
                break
        else:
            target = member_prefix_match(key, members)
            if target is None:
                target = [key, []]
                groups.append(target)
        target[1].extend(by_name[key])
        if is_member(key, target[0]):
            members[key] = target
    return [ts for _, ts in groups]


DESCRIPTOR_MIN_LENGTH = 5    # shorter normalized descriptors never merge


def _dominant_descriptor(txns, normalized):
    """Most common non-empty normalized description; ties → smallest string."""
    counts = Counter()
    for t in txns:
        d = normalized(t.description)
        if d:
            counts[d] += 1
    if not counts:
        return ''
    top = max(counts.values())
    return min(d for d, n in counts.items() if n == top)


def merge_by_descriptor(groups):
    """Merge merchant groups that are one merchant renamed by Plaid.

    Plaid's merchant-name enrichment can change mid-history while the card
    descriptor (`description`) stays the same, splitting one bill into an old
    group that looks lapsed and a new one too short to be a stream. Groups are
    merged only when that is clearly what happened:

    - they share a dominant normalized descriptor of at least
      DESCRIPTOR_MIN_LENGTH characters — by exact equality only: fuzzy
      matching here would put the quadratic cost knowledge 029 moved to sync
      time back on every request;
    - the groups sharing it carry at most one distinct merchant_entity_id
      between them — two Plaid entities are two merchants (knowledge 032), and
      a bucket with two is ambiguous, so it merges nothing at all;
    - they are on the same side (charges vs deposits, by the signed median
      `_build_stream` uses);
    - no two of that side's groups overlap in time: a rename is sequential.
      If any two do, nothing on that side merges — a concurrent group means
      the descriptor is shared by more than one merchant, so even sequential
      neighbours stay split (today's behaviour, never a false merge).

    Pure: the input lists are not mutated. The result does not depend on the
    order of the input groups.
    """
    groups = [list(g) for g in groups]
    cache = {}

    def normalized(text):
        if text not in cache:
            cache[text] = normalize_merchant(text or '')
        return cache[text]

    buckets = defaultdict(list)
    merged = []
    for group in groups:
        descriptor = _dominant_descriptor(group, normalized)
        if len(descriptor) < DESCRIPTOR_MIN_LENGTH:
            merged.append(group)
        else:
            buckets[descriptor].append(group)

    for descriptor in sorted(buckets):
        bucket = buckets[descriptor]
        entities = {t.merchant_entity_id for g in bucket for t in g
                    if t.merchant_entity_id}
        if len(bucket) == 1 or len(entities) > 1:
            merged.extend(bucket)
            continue
        sides = defaultdict(list)
        for group in bucket:
            sides[_median([t.amount for t in group]) < 0].append(group)
        for inflow in (False, True):
            side = sorted(sides[inflow], key=_group_order)
            spans = [(min(t.date for t in g), max(t.date for t in g)) for g in side]
            sequential = all(later[0] > earlier[1]
                             for earlier, later in zip(spans, spans[1:]))
            if len(side) > 1 and sequential:
                merged.append([t for g in side for t in g])
            else:
                merged.extend(side)
    return merged


def _group_order(group):
    """Total order for merging: earliest date, latest date, display name,
    size, then every description — so input order never decides a merge."""
    return (
        min(t.date for t in group),
        max(t.date for t in group),
        _display_name(group),
        len(group),
        tuple(sorted(t.description or '' for t in group)),
        tuple(sorted(str(t.amount) for t in group)),
        tuple(sorted(t.merchant_entity_id or '' for t in group)),
    )


def _month_index(d):
    return d.year * 12 + d.month


def _gap_is_regular(earlier, later, nominal, tol, skips=False):
    """Whether the gap between two consecutive occurrences fits the bucket.

    Within the bucket's tolerance always fits. With `skips`, a weekly gap also
    fits within the tolerance of one or two skipped sessions
    (WEEKLY_SKIP_MULTIPLES: 14 or 21 ± 2 days); _classify_cadence decides when
    to allow that. A monthly gap also fits when the two dates fall in
    consecutive calendar months (December → January included) and are within
    MONTHLY_CALENDAR_SLACK days of 30: a bill paid once a month on a drifting
    day. A gap inside one month, one that skips a month, or one
    outside 15–45 days still does not. Months are those of `date`, Plaid's
    posting date.
    """
    gap = (later - earlier).days
    if abs(gap - nominal) <= tol:
        return True
    if nominal == _WEEKLY_NOMINAL:
        return skips and any(abs(gap - k * nominal) <= tol for k in WEEKLY_SKIP_MULTIPLES)
    return (
        nominal == _MONTHLY_NOMINAL
        and _month_index(later) - _month_index(earlier) == 1
        and abs(gap - nominal) <= MONTHLY_CALENDAR_SLACK
    )


def _weekday_share(dates):
    """Fraction of `dates` that fall on their most common weekday."""
    return Counter(d.weekday() for d in dates).most_common(1)[0][1] / len(dates)


def _classify_cadence(dates):
    """Map the median gap between sorted, distinct occurrence dates to a cadence
    bucket, requiring most gaps to be regular (`_gap_is_regular`). Returns
    (name, nominal_days) or None.

    A weekly stream that fails may retry with skipped sessions allowed, if it
    keeps its weekday (WEEKLY_SKIP_MIN_WEEKDAY_SHARE).
    """
    pairs = list(zip(dates, dates[1:]))
    if not pairs:
        return None
    med = _median([(b - a).days for a, b in pairs])
    for name, nominal, tol in CADENCES:
        if abs(med - nominal) > tol:
            continue
        required = MIN_OCCURRENCES_ANNUAL if name == 'annual' else MIN_OCCURRENCES
        if len(dates) < required:
            return None
        within = sum(1 for a, b in pairs if _gap_is_regular(a, b, nominal, tol))
        if (within / len(pairs) < GAP_REGULARITY and nominal == _WEEKLY_NOMINAL
                and _weekday_share(dates) >= WEEKLY_SKIP_MIN_WEEKDAY_SHARE):
            within = sum(1 for a, b in pairs
                         if _gap_is_regular(a, b, nominal, tol, skips=True))
        if within / len(pairs) >= GAP_REGULARITY:
            return name, nominal
        return None  # median fit the bucket but the gaps are irregular
    return None


def _is_new_monthly_pair(dates):
    """Whether two distinct dates look like the first two charges of a new
    monthly bill: consecutive calendar months, a gap within the strict monthly
    tolerance (no MONTHLY_CALENDAR_SLACK). Recency is the caller's `active`.
    """
    if len(dates) != 2:
        return False
    earlier, later = dates
    _name, nominal, tol = _MONTHLY_BUCKET
    return (_month_index(later) - _month_index(earlier) == 1
            and abs((later - earlier).days - nominal) <= tol)


def _inactive_after_days(nominal):
    """Days past the last charge after which a stream is inactive.

    1.5 × cadence, except weekly: a weekly stream may skip sessions
    (WEEKLY_SKIP_MULTIPLES), so it stays active through the largest gap the
    bucket calls regular — 3 × 7 + 2 = 23 days.
    """
    if nominal == _WEEKLY_NOMINAL:
        return max(WEEKLY_SKIP_MULTIPLES) * nominal + _WEEKLY_BUCKET[2]
    return INACTIVE_MULTIPLIER * nominal


def _build_stream(txns, today, fallback_cadence=None, pair=False):
    """Build a stream dict from one merchant group, or None if the group
    isn't recurring.

    `fallback_cadence` — a (name, nominal days) pair — is used only when no
    cadence is detected: a user rule asserting that an irregular stream recurs
    (app/recurring_rules.py). A detected cadence always wins, so a rule's
    annual stream stays annual. The stream records which happened in
    `cadence_forced`.

    `pair` — accept exactly two charges as a new monthly stream when
    `_is_new_monthly_pair` holds, below MIN_OCCURRENCES. Only the exact-amount
    split passes it (app/bills.py::_split_by_amount), where the two charges
    share one exact amount. Such a stream has `new` set.
    """
    dates = sorted({t.date for t in txns})  # same-day charges = one occurrence
    cadence = _classify_cadence(dates)
    new = cadence is None and pair and _is_new_monthly_pair(dates)
    if new:
        cadence = _MONTHLY_BUCKET[:2]
    forced = cadence is None and fallback_cadence is not None
    if forced:
        cadence = fallback_cadence
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
        'cadence_forced': forced,
        'new': new,
        'amount': median_amount,
        'varies': varies,
        'is_inflow': median_amount < 0,
        'last_date': last_date,
        'next_date': last_date + timedelta(days=nominal),
        'count': len(txns),
        'active': (today - last_date).days <= _inactive_after_days(nominal),
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

    `groups` is an iterable of row lists; each list is one merchant. Groups
    that are one merchant renamed by Plaid are merged first
    (`merge_by_descriptor`).
    """
    streams = []
    for group in merge_by_descriptor(groups):
        stream = _build_stream(group, today)
        if stream is not None:
            streams.append(stream)
    streams.sort(key=lambda s: (not s['active'], -abs(s['amount'])))
    return streams
