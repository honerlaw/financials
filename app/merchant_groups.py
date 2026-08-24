"""Persisted merchant grouping — the DB-backed half of subscription detection.

`app/subscriptions.py` stays a pure module: it knows how to decide whether two
merchant keys are the same merchant, and nothing about storage. This module owns
the storage, and exists because that decision is quadratic.

Grouping compares every distinct merchant key against every group found so far,
which is O(keys^2) `SequenceMatcher` calls — measured at 5s for 1000 distinct
merchants, 20s for 2000, 45s for 3000, with both /subscriptions and /bills
paying it on every request. The cost is driven by *distinct merchants*, not
transaction count, so it grows permanently as one-off purchases accumulate.

The fix is to do the matching once, at sync time, and keep the answer. A key
that has already been assigned to a group never gets matched again; only
genuinely new keys are compared, against the frozen canonical keys of existing
groups. Steady state is a handful of new merchants per sync.

Everything date-dependent — `active`, `next_date`, payment status — is
deliberately NOT stored. It is recomputed per request from the grouped
transactions, so the index cannot go stale merely because the calendar moved.
"""

from collections import Counter, defaultdict

from flask import current_app

from app import db
from app.models import MerchantGroup, MerchantGroupKey, Transaction
from app.subscriptions import (
    GROUPING_ALGO_VERSION,
    _group_transactions,
    _similar,
    grouping_key,
    normalize_merchant,
)
from difflib import SequenceMatcher


def backfill_missing_keys():
    """Populate `merchant_key` on rows that predate the column.

    Returns the number of rows written. The migration adds the column as NULL
    because `normalize_merchant` is Python and cannot run in SQL, so the first
    pass after deploy does the work instead.
    """
    rows = Transaction.query.filter(Transaction.merchant_key.is_(None)).all()
    for txn in rows:
        # '' means "processed, but this row has no groupable merchant" — a
        # purely numeric memo, or no name at all. It must be distinguishable
        # from NULL ("never processed"), because is_index_usable() treats NULL
        # as work outstanding: storing NULL here would make one unkeyable
        # transaction hold the whole index hostage, sending every page load
        # down the O(n^2) path forever. The in-memory grouper likewise drops
        # these rows rather than grouping them.
        txn.merchant_key = grouping_key(txn)
    return len(rows)


def _stored_algo_version():
    """The algorithm version the existing index was built with, or None."""
    row = MerchantGroup.query.first()
    return None if row is None else row.algo_version


def _unindexed_keys():
    """Distinct non-null merchant keys with no group yet.

    This is the trigger. It is deliberately not `added_count or removed_count`
    from the sync: `_upsert_transactions` returns a count of newly *inserted*
    rows only, so a sync carrying only modified transactions — a pending charge
    resolving, Plaid correcting a merchant name — reports zero while a key has
    in fact changed. Asking the data costs one indexed query and is also correct
    under backfills and manual edits.
    """
    indexed = db.session.query(MerchantGroupKey.key)
    rows = (
        db.session.query(Transaction.merchant_key)
        .filter(Transaction.merchant_key.isnot(None))
        .filter(Transaction.merchant_key != '')
        .filter(~Transaction.merchant_key.in_(indexed))
        .distinct()
        .all()
    )
    return sorted(key for (key,) in rows)


def _representative_name(key):
    """The name an entity-keyed group should be known by for matching.

    A group's canonical_key must be a *normalized name*, never the raw
    'entity:...' string, because it is what later name keys fuzzy-match
    against. Store the entity id there and "netflix" can never join the Netflix
    entity group: the stream splits in two, and each half may drop below
    MIN_OCCURRENCES and disappear from both pages entirely. This mirrors
    `_group_key` in app/subscriptions.py, which picks the most common
    normalized name across the group.

    Returns '' when the entity's transactions carry no usable name, in which
    case the caller falls back to the entity key itself.
    """
    rows = Transaction.query.filter_by(merchant_key=key, removed=False).all()
    names = Counter(
        normalize_merchant(t.merchant_name or t.description) for t in rows
    )
    names.pop('', None)
    return names.most_common(1)[0][0] if names else ''


def _match_name(name, canonical, allow_entity_groups=True):
    """The group whose canonical key fuzzy-matches `name`, or None.

    `canonical` maps canonical_key -> (group_id, from_entity). Canonical keys
    that are still raw entity ids (an entity whose transactions carried no name
    at all) are skipped: matching a name against 'entity:abc123' by string
    similarity is meaningless.

    `allow_entity_groups=False` additionally refuses groups opened from a
    merchant_entity_id. Two distinct entity ids must never merge, however alike
    their display names: Plaid has already said they are different merchants,
    and the in-memory grouper never compares entity groups against each other.
    Allowing it makes the two paths report different subscriptions from the
    same data — two 2-charge "Amazon" entities merge into one 4-charge stream
    that clears MIN_OCCURRENCES on the indexed path and does not exist on the
    in-memory one.
    """
    if not name:
        return None
    matcher = SequenceMatcher(None, '', name, autojunk=False)
    for canonical_key, (group_id, from_entity) in canonical.items():
        if canonical_key.startswith('entity:'):
            continue
        if from_entity and not allow_entity_groups:
            continue
        if _similar(canonical_key, name, matcher):
            return group_id
    return None


def update_index():
    """Bring the merchant-group index up to date. Returns a summary dict.

    Cheap and safe to call on every sync: with nothing new it runs two indexed
    queries and returns. A `GROUPING_ALGO_VERSION` mismatch rebuilds the whole
    index exactly once, so tuning FUZZY_THRESHOLD or normalize_merchant can
    never leave a silently stale grouping behind.
    """
    rebuilt = False
    stored = _stored_algo_version()
    if stored is not None and stored != GROUPING_ALGO_VERSION:
        MerchantGroupKey.query.delete()
        MerchantGroup.query.delete()
        # Clearing the groups is not enough. A version bump exists precisely
        # because normalize_merchant or the matching rule changed, and every
        # stored merchant_key was computed by the OLD normalizer. Regrouping
        # stale keys reproduces the old grouping under a new version stamp —
        # the rebuild would report success while changing nothing. Null them so
        # backfill_missing_keys recomputes each one.
        Transaction.query.update(
            {Transaction.merchant_key: None}, synchronize_session=False,
        )
        db.session.flush()
        rebuilt = True

    backfilled = backfill_missing_keys()
    db.session.flush()

    new_keys = _unindexed_keys()
    if not new_keys and not backfilled and not rebuilt:
        return {'rebuilt': False, 'backfilled': 0, 'new_keys': 0, 'new_groups': 0}

    canonical = {
        g.canonical_key: (g.id, g.from_entity)
        for g in MerchantGroup.query.all()
    }

    # Entity keys first, exactly as _group_transactions seeds its group list
    # from merchant_entity_id before merging name keys. Order matters: a name
    # key can only join an entity group that already exists.
    entity_keys = [k for k in new_keys if k.startswith('entity:')]
    name_keys = [k for k in new_keys if not k.startswith('entity:')]

    new_groups = 0
    for key in entity_keys:
        name = _representative_name(key)
        # May join a group opened from a plain name (Plaid starting to supply an
        # entity id for a merchant already seen without one), but never another
        # entity's group.
        group_id = _match_name(name, canonical, allow_entity_groups=False)
        if group_id is None:
            group = MerchantGroup(
                canonical_key=name or key, algo_version=GROUPING_ALGO_VERSION,
                from_entity=True,
            )
            db.session.add(group)
            db.session.flush()          # need the id before the key row
            group_id = group.id
            canonical[group.canonical_key] = (group_id, True)
            new_groups += 1
        db.session.add(MerchantGroupKey(key=key, group_id=group_id))

    for key in name_keys:
        group_id = _match_name(key, canonical)
        if group_id is None:
            group = MerchantGroup(
                canonical_key=key, algo_version=GROUPING_ALGO_VERSION,
                from_entity=False,
            )
            db.session.add(group)
            db.session.flush()
            group_id = group.id
            canonical[key] = (group_id, False)
            new_groups += 1
        db.session.add(MerchantGroupKey(key=key, group_id=group_id))

    db.session.flush()
    return {
        'rebuilt': rebuilt,
        'backfilled': backfilled,
        'new_keys': len(new_keys),
        'new_groups': new_groups,
    }


def is_index_usable():
    """True when the index covers every live transaction at the current version.

    False sends the caller down the in-memory path. Checked per request because
    a partially-built index would silently drop merchants from both pages, and a
    missing subscription is far worse than a slow one.
    """
    if _stored_algo_version() != GROUPING_ALGO_VERSION:
        return False
    missing = (
        db.session.query(Transaction.id)
        .filter(Transaction.removed.is_(False))
        .filter(Transaction.merchant_key.isnot(None))
        .filter(Transaction.merchant_key != '')     # '' = nothing to group
        .filter(~Transaction.merchant_key.in_(db.session.query(MerchantGroupKey.key)))
        .first()
    )
    if missing is not None:
        return False
    unkeyed = (
        db.session.query(Transaction.id)
        .filter(Transaction.removed.is_(False))
        .filter(Transaction.merchant_key.is_(None))
        .first()
    )
    return unkeyed is None


def grouped_transactions():
    """Live transactions bucketed by their persisted group. No fuzzy matching.

    Returns a list of transaction lists, one per merchant — the same shape
    `_group_transactions` returns, so the detectors cannot tell the difference.
    """
    key_to_group = dict(
        db.session.query(MerchantGroupKey.key, MerchantGroupKey.group_id).all()
    )
    groups = defaultdict(list)
    rows = Transaction.query.filter_by(removed=False).all()
    for txn in rows:
        group_id = key_to_group.get(txn.merchant_key)
        if group_id is not None:
            groups[group_id].append(txn)
    return list(groups.values())


def _in_memory_fallback():
    """Group the slow way. Correct, just O(distinct merchants squared)."""
    live = Transaction.query.filter_by(removed=False).all()
    return _group_transactions(live), False


def groups_for_detection():
    """The grouping /subscriptions and /bills should use, warming the index if
    it is cold.

    Returns (groups, used_index). When the index is usable this is a pair of
    indexed queries and no fuzzy matching at all. When it is not — the first
    load after deploy, or straight after a version bump — the index is built
    now and used; the caller commits.

    The in-memory path stays reachable as the last resort so a failure to build
    can never render an empty page: a slow /subscriptions is a bad day, an
    empty one looks like lost data.
    """
    if is_index_usable():
        return grouped_transactions(), True

    try:
        # Savepoint, not a bare try: on Postgres a statement that fails inside an
        # open transaction leaves it aborted, and every later statement on that
        # connection raises until someone rolls back. Without this the fallback
        # query below would itself raise and the page would go from slow to
        # broken — the exact outcome this fallback exists to prevent. SQLite is
        # forgiving here, so no test on this suite's backend would catch it.
        with db.session.begin_nested():
            update_index()
    except Exception:
        current_app.logger.exception('merchant group index build failed')
        return _in_memory_fallback()

    if is_index_usable():
        return grouped_transactions(), True

    # Built without error yet still unusable — do not guess, just serve the
    # correct answer the slow way and say so.
    current_app.logger.warning(
        'merchant group index still unusable after build; '
        'falling back to in-memory grouping'
    )
    return _in_memory_fallback()
