"""Tests for the persisted merchant-group index.

The index exists to remove an O(distinct-merchants^2) fuzzy match from every
/subscriptions and /bills request. These tests pin the two properties that make
that safe: the indexed grouping agrees with the in-memory grouping the detector
contract is written against, and a group assignment never moves once made.
"""

from datetime import date, timedelta
from decimal import Decimal
from difflib import SequenceMatcher

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
