"""Tests for the persisted merchant-group index.

The index exists to remove an O(distinct-merchants^2) fuzzy match from every
/subscriptions and /bills request. These tests pin the two properties that make
that safe: the indexed grouping agrees with the in-memory grouping the detector
contract is written against, and a group assignment never moves once made.
"""

from datetime import date, timedelta
from unittest import mock
from decimal import Decimal
from difflib import SequenceMatcher

from sqlalchemy import event, text

import pytest

from app.bills import detect_bills, detect_bills_from_groups
from app.merchant_groups import (
    grouped_transactions,
    groups_for_detection,
    is_index_usable,
    update_index,
)
from app.models import db, Institution, MerchantGroup, MerchantGroupKey, Transaction
from app.subscriptions import (
    FUZZY_THRESHOLD,
    GROUPING_ALGO_VERSION,
    _similar,
    detect_subscriptions,
    detect_subscriptions_from_groups,
    grouping_key,
)
from tests.test_subscriptions import FakeTxn, monthly_txns

TODAY = date(2026, 6, 1)


def _persist(txns):
    """Write FakeTxn fixtures out as real rows, keyed the way sync keys them."""
    inst = Institution(name='Test Bank', slug='test_bank',
                       access_token='tok', item_id='item-1')
    db.session.add(inst)
    db.session.flush()
    for i, t in enumerate(txns):
        db.session.add(Transaction(
            plaid_transaction_id='txn-%d' % i,
            institution_id=inst.id,
            account_id=t.account_id,
            date=t.date,
            description=t.description,
            merchant_name=t.merchant_name,
            merchant_entity_id=t.merchant_entity_id,
            amount=t.amount,
            removed=t.removed,
            merchant_key=grouping_key(t) or None,
        ))
    db.session.commit()
    return Transaction.query.all()


# ── Corpora, reusing the fixtures the detector contract is written against ───

def _variants():
    """Merchant-name variants that must collapse into one stream."""
    return (monthly_txns(2, merchant_name='NETFLIX.COM 866-579-7172')
            + monthly_txns(2, start=date(2026, 3, 5), merchant_name='Netflix'))


def _entity_and_name():
    """An entity-id stream plus bare-name charges for the same merchant."""
    return (monthly_txns(2, merchant_name='Spotify', merchant_entity_id='ent-sp')
            + monthly_txns(2, start=date(2026, 3, 5), merchant_name='Spotify USA'))


def _mixed():
    """Several unrelated streams plus an irregular merchant that must not match."""
    txns = monthly_txns(4, merchant_name='Netflix')
    txns += monthly_txns(4, start=date(2026, 1, 12), merchant_name='Rent',
                         amount='1800.00')
    txns += monthly_txns(3, start=date(2026, 2, 2), merchant_name='Paycheck',
                         amount='-2400.00')
    for i, gap in enumerate([0, 3, 9, 11, 20, 23]):
        txns.append(FakeTxn(date(2026, 1, 4) + timedelta(days=gap),
                            merchant_name='Corner Grocery', amount='31.00'))
    return txns


CORPORA = {
    'variants': _variants,
    'entity_and_name': _entity_and_name,
    'mixed': _mixed,
}


@pytest.mark.parametrize('corpus', sorted(CORPORA))
def test_indexed_subscriptions_match_in_memory(app, corpus):
    """The success-criteria parity bar: the same rows through both paths."""
    with app.app_context():
        rows = _persist(CORPORA[corpus]())
        expected = detect_subscriptions(rows, TODAY)

        update_index()
        db.session.commit()
        assert is_index_usable()

        actual = detect_subscriptions_from_groups(grouped_transactions(), TODAY)
        assert [s['name'] for s in actual] == [s['name'] for s in expected]
        assert [s['cadence'] for s in actual] == [s['cadence'] for s in expected]
        assert [s['count'] for s in actual] == [s['count'] for s in expected]


@pytest.mark.parametrize('corpus', sorted(CORPORA))
def test_indexed_bills_match_in_memory(app, corpus):
    with app.app_context():
        rows = _persist(CORPORA[corpus]())
        expected = detect_bills(rows, TODAY)

        update_index()
        db.session.commit()

        actual = detect_bills_from_groups(grouped_transactions(), TODAY)
        assert [b['name'] for b in actual] == [b['name'] for b in expected]
        assert ([b['payment_status'] for b in actual]
                == [b['payment_status'] for b in expected])


def test_name_key_joins_the_entity_group(app):
    """A bare-name charge must land in the entity group for the same merchant.

    Storing 'entity:<id>' as a group's canonical key instead of its
    representative name silently splits the stream in two, and each half can
    then fall below MIN_OCCURRENCES and vanish from both pages.
    """
    with app.app_context():
        _persist(_entity_and_name())
        update_index()
        db.session.commit()

        assert MerchantGroup.query.count() == 1
        keys = {k.key for k in MerchantGroupKey.query.all()}
        assert 'entity:ent-sp' in keys
        assert any(not k.startswith('entity:') for k in keys)


def test_new_merchant_never_reassigns_an_existing_group(app):
    """Stability: adding merchants must not move transactions already grouped."""
    with app.app_context():
        _persist(_mixed())
        update_index()
        db.session.commit()
        before = {k.key: k.group_id for k in MerchantGroupKey.query.all()}

        inst = Institution.query.first()
        for i, name in enumerate(['Hulu', 'Disney Plus', 'Con Edison']):
            db.session.add(Transaction(
                plaid_transaction_id='late-%d' % i, institution_id=inst.id,
                account_id='acc-1', date=date(2026, 5, 20), description=name,
                merchant_name=name, amount=Decimal('12.00'),
                merchant_key=grouping_key(FakeTxn(date(2026, 5, 20),
                                                  merchant_name=name)),
            ))
        db.session.commit()
        update_index()
        db.session.commit()

        after = {k.key: k.group_id for k in MerchantGroupKey.query.all()}
        for key, group_id in before.items():
            assert after[key] == group_id, 'key %r was reassigned' % key


def test_quiet_update_does_no_work(app):
    """A sync that changed nothing must not touch the index."""
    with app.app_context():
        _persist(_mixed())
        update_index()
        db.session.commit()
        groups_before = MerchantGroup.query.count()
        keys_before = MerchantGroupKey.query.count()

        result = update_index()
        db.session.commit()

        assert result == {'rebuilt': False, 'backfilled': 0,
                          'new_keys': 0, 'new_groups': 0}
        assert MerchantGroup.query.count() == groups_before
        assert MerchantGroupKey.query.count() == keys_before


def test_version_bump_rebuilds_exactly_once(app, monkeypatch):
    with app.app_context():
        _persist(_mixed())
        update_index()
        db.session.commit()
        assert {g.algo_version for g in MerchantGroup.query.all()} == \
            {GROUPING_ALGO_VERSION}

        bumped = GROUPING_ALGO_VERSION + 1
        monkeypatch.setattr('app.merchant_groups.GROUPING_ALGO_VERSION', bumped)

        first = update_index()
        db.session.commit()
        assert first['rebuilt'] is True
        assert {g.algo_version for g in MerchantGroup.query.all()} == {bumped}

        second = update_index()
        db.session.commit()
        assert second['rebuilt'] is False
        assert second['new_keys'] == 0


def test_cold_index_falls_back_and_warms(app):
    """Rows with no merchant_key must still render, and warm the index."""
    with app.app_context():
        rows = _persist(_mixed())
        for txn in rows:
            txn.merchant_key = None
        db.session.commit()
        assert not is_index_usable()

        groups, used_index = groups_for_detection()
        db.session.commit()

        streams = detect_subscriptions_from_groups(groups, TODAY)
        assert [s['name'] for s in streams] == \
            [s['name'] for s in detect_subscriptions(rows, TODAY)]
        assert used_index is True          # built on demand, then used
        assert is_index_usable()


def test_build_failure_falls_back_to_in_memory_grouping(app):
    """The real fallback branch: the index build raises, the page still renders.

    Distinct from test_cold_index_falls_back_and_warms, which exercises
    warm-on-demand (the build succeeds). This one pins the property that
    actually protects the user — an index that cannot be built degrades to a
    slow page, never an empty one.
    """
    with app.app_context():
        rows = _persist(_mixed())
        for txn in rows:
            txn.merchant_key = None
        db.session.commit()

        with mock.patch('app.merchant_groups.update_index',
                        side_effect=RuntimeError('index build exploded')):
            groups, used_index = groups_for_detection()

        assert used_index is False
        streams = detect_subscriptions_from_groups(groups, TODAY)
        assert [s['name'] for s in streams] == \
            [s['name'] for s in detect_subscriptions(rows, TODAY)]
        assert MerchantGroup.query.count() == 0


def test_unusable_after_successful_build_still_falls_back(app):
    """Built without error yet still unusable — serve the slow correct answer."""
    with app.app_context():
        rows = _persist(_mixed())
        db.session.commit()

        with mock.patch('app.merchant_groups.is_index_usable', return_value=False):
            groups, used_index = groups_for_detection()

        assert used_index is False
        streams = detect_subscriptions_from_groups(groups, TODAY)
        assert [s['name'] for s in streams] == \
            [s['name'] for s in detect_subscriptions(rows, TODAY)]


QUIET_SYNC_SELECTS = 3
"""_stored_algo_version + backfill_missing_keys + _unindexed_keys.

Asserted exactly, not as an upper bound: a slack bound lets a 3->4 regression
pass silently, which is the same undetected drift that let "one indexed query"
sit unchallenged in the proposal. Change this deliberately if the
implementation legitimately changes.
"""


def _count_selects(fn):
    """Run `fn`, returning (result, number of SELECT statements issued)."""
    counter = {'n': 0}

    def _tally(conn, cursor, statement, params, context, executemany):
        if statement.lstrip().upper().startswith('SELECT'):
            counter['n'] += 1

    engine = db.session.get_bind()
    event.listen(engine, 'before_cursor_execute', _tally)
    try:
        result = fn()
    finally:
        event.remove(engine, 'before_cursor_execute', _tally)
    return result, counter['n']


def test_quiet_update_cost_does_not_grow_with_the_corpus(app):
    """The property C2 actually protects: per-sync cost is O(1) in corpus size.

    Counting queries against a single fixture would only pin "3 for this
    fixture". Comparing two corpora an order of magnitude apart is what shows
    the cost is a constant rather than something that scales with merchants.
    """
    with app.app_context():
        _persist(_mixed())
        update_index()
        db.session.commit()
        _, small = _count_selects(update_index)
        db.session.commit()

        inst = Institution.query.first()
        for i in range(200):
            name = 'Merchant %d' % i
            txn = Transaction(
                plaid_transaction_id='bulk-%d' % i, institution_id=inst.id,
                account_id='acc-1', date=date(2026, 5, 20), description=name,
                merchant_name=name, amount=Decimal('9.00'),
            )
            txn.merchant_key = grouping_key(txn)
            db.session.add(txn)
        db.session.commit()
        update_index()
        db.session.commit()
        _, large = _count_selects(update_index)
        db.session.commit()

        assert small == QUIET_SYNC_SELECTS, (
            'quiet sync issued %d SELECTs, expected %d' % (small, QUIET_SYNC_SELECTS)
        )
        assert large == small, (
            'quiet-sync cost grew from %d to %d SELECTs as the corpus grew; it '
            'must not scale with merchant count' % (small, large)
        )


def test_sql_failure_during_build_leaves_the_session_usable(app):
    """A real SQL error, not a mocked function, must not break the page.

    test_build_failure_falls_back_to_in_memory_grouping patches update_index
    wholesale, so no statement ever reaches the database and the session is
    never dirtied. That cannot catch the failure that matters: on Postgres a
    failed statement aborts the surrounding transaction, and without the
    savepoint in groups_for_detection the fallback's own query would raise.
    SQLite tolerates this, so this test documents the contract and pins the
    fallback's output; the savepoint is what makes it hold on Postgres.
    """
    with app.app_context():
        rows = _persist(_mixed())
        for txn in rows:
            txn.merchant_key = None
        db.session.commit()

        def _explode():
            db.session.execute(text('SELECT * FROM table_that_does_not_exist'))

        with mock.patch('app.merchant_groups.update_index', side_effect=_explode):
            groups, used_index = groups_for_detection()

        assert used_index is False
        streams = detect_subscriptions_from_groups(groups, TODAY)
        assert [s['name'] for s in streams] == \
            [s['name'] for s in detect_subscriptions(rows, TODAY)]

        # The session must still be usable afterwards — this is the assertion
        # that would fail on Postgres without the savepoint.
        assert Transaction.query.count() == len(rows)


def test_removed_transactions_do_not_break_the_index(app):
    with app.app_context():
        txns = _mixed()
        txns[0].removed = True
        rows = _persist(txns)
        update_index()
        db.session.commit()

        expected = detect_subscriptions(rows, TODAY)
        actual = detect_subscriptions_from_groups(grouped_transactions(), TODAY)
        assert [s['count'] for s in actual] == [s['count'] for s in expected]


# ── The prefilter must not change the predicate ──────────────────────────────

def _reference_similar(a, b):
    """`_similar` as it read before the speed work, for differential testing."""
    if a == b:
        return True
    if len(a) >= 5 and len(b) >= 5 and (a.startswith(b) or b.startswith(a)):
        return True
    return SequenceMatcher(None, a, b).ratio() >= FUZZY_THRESHOLD


def test_prefilter_preserves_the_similarity_predicate():
    words = ['netflix', 'netflx', 'netflixcom', 'spotify', 'spotify usa',
             'rent', 'renting', 'corner grocery', 'corner grocer', 'a', 'ab',
             'con edison', 'conedison', 'paycheck', 'pay check', '']
    for a in words:
        for b in words:
            if not a and not b:
                continue
            assert _similar(a, b) == _reference_similar(a, b), (a, b)
