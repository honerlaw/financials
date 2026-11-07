"""A name key joins a group through a member key that is a word prefix of it.

The card network can append a city and country to a descriptor whose plain
form already joined a group (`IN *ACME WIDGETS` -> `IN *ACME WIDGETS ANYTOWN
USA`). Grouping compares a new key only with each group's representative, so
the suffixed key used to open a group of its own. Both grouping paths now share
app.subscriptions.member_prefix_match. All fixtures are fictional, and each
asserts its own _similar preconditions so it cannot pass with the rule removed.
"""

from datetime import date

import app.subscriptions as subs
from app.merchant_groups import grouped_transactions, update_index
from app.models import MerchantGroup, MerchantGroupKey, Transaction, db
from app.subscriptions import (
    GROUPING_ALGO_VERSION,
    MEMBER_PREFIX_MIN_LENGTH,
    _group_transactions,
    _similar,
    grouping_key,
)
from tests.test_merchant_groups import _persist
from tests.test_subscriptions import FakeTxn, monthly_txns

PLAIN = 'IN *ACME WIDGETS'
SUFFIXED = 'IN *ACME WIDGETS ANYTOWN USA'


def _target(entity=None, suffixed=True, plain_removed=False):
    """Enriched rows, one un-enriched plain row and one un-enriched suffixed row."""
    txns = monthly_txns(3, merchant_name='Acme Widgets', description=PLAIN,
                        merchant_entity_id=entity)
    txns.append(FakeTxn(date(2026, 4, 5), description=PLAIN, removed=plain_removed))
    if suffixed:
        txns.append(FakeTxn(date(2026, 5, 9), description=SUFFIXED))
    return txns


def _partition(groups):
    """Groups as a set of frozensets of (date, amount, description)."""
    return {frozenset((t.date, t.amount, t.description) for t in g) for g in groups}


def _in_memory(txns):
    return _partition(_group_transactions([t for t in txns if not t.removed]))


def _group_of(groups, description):
    [group] = [g for g in groups if any(d == description for _, _, d in g)]
    return group


# ── in-memory grouping ───────────────────────────────────────────────────────

def test_preconditions_of_the_target_case():
    assert _similar('acme widgets', 'in acme widgets') is True
    assert _similar('acme widgets', 'in acme widgets anytown usa') is False


def test_suffixed_key_joins_through_a_member_in_a_name_group():
    assert len(_in_memory(_target())) == 1


def test_suffixed_key_joins_through_a_member_in_an_entity_group():
    assert len(_in_memory(_target(entity='ent-acme'))) == 1


def test_without_the_rule_the_suffixed_key_splits(monkeypatch):
    monkeypatch.setattr(subs, 'member_prefix_match', lambda key, members: None)
    assert len(_in_memory(_target())) == 2


def _min_length_corpus():
    # Entity representative 'xabcd'; 'abcd' joins it by ratio, not by prefix.
    assert _similar('xabcd', 'abcd') is True and not 'xabcd'.startswith('abcd')
    assert _similar('xabcd', 'abcd xyz') is False
    return (monthly_txns(3, merchant_name='Xabcd', merchant_entity_id='ent-x')
            + [FakeTxn(date(2026, 4, 9), description='ABCD'),
               FakeTxn(date(2026, 5, 9), description='ABCD XYZ')])


def test_a_member_prefix_shorter_than_the_minimum_never_joins():
    assert len('abcd') < MEMBER_PREFIX_MIN_LENGTH
    assert len(_in_memory(_min_length_corpus())) == 2


def test_the_minimum_is_what_keeps_it_apart(monkeypatch):
    monkeypatch.setattr(subs, 'MEMBER_PREFIX_MIN_LENGTH', 0)
    assert len(_in_memory(_min_length_corpus())) == 1


def test_word_boundary():
    # 'in acme widget' joins representative 'acme widget' by ratio; the key
    # 'in acme widgetry bar' extends it by characters but not by words.
    assert _similar('acme widget', 'in acme widget') is True
    assert _similar('acme widget', 'in acme widgetry bar') is False
    assert 'in acme widgetry bar'.startswith('in acme widget')
    txns = (monthly_txns(3, merchant_name='Acme Widget', merchant_entity_id='ent-w')
            + [FakeTxn(date(2026, 4, 9), description='IN *ACME WIDGET'),
               FakeTxn(date(2026, 5, 9), description='IN *ACME WIDGETRY BAR')])
    assert len(_in_memory(txns)) == 2


def _hub_corpus():
    # 'amazon' joins the 'amazon prime' entity group by reverse prefix.
    assert _similar('amazon prime', 'amazon') is True
    assert _similar('amazon prime', 'amazon fresh delivery') is False
    return (monthly_txns(3, merchant_name='Amazon Prime', merchant_entity_id='ent-amz')
            + [FakeTxn(date(2026, 4, 9), description='AMAZON'),
               FakeTxn(date(2026, 5, 9), description='AMAZON FRESH DELIVERY')])


def test_a_prefix_of_the_representative_is_not_a_member():
    assert len(_in_memory(_hub_corpus())) == 2


def test_without_the_guard_it_would_be_a_hub(monkeypatch):
    monkeypatch.setattr(subs, 'is_member', lambda key, representative: True)
    assert len(_in_memory(_hub_corpus())) == 1


# ── indexed path ─────────────────────────────────────────────────────────────

def _indexed(app, txns):
    with app.app_context():
        _persist(txns)
        update_index()
        db.session.commit()
        return _partition(grouped_transactions())


def test_algo_version_bumped_for_the_rule():
    assert GROUPING_ALGO_VERSION == 2


def test_cold_index_matches_in_memory_name_group(app):
    txns = _target()
    assert _indexed(app, txns) == _in_memory(txns)
    assert len(_in_memory(txns)) == 1


def test_cold_index_matches_in_memory_entity_group(app):
    txns = _target(entity='ent-acme')
    assert _indexed(app, txns) == _in_memory(txns)
    assert len(_in_memory(txns)) == 1


def test_a_removed_rows_key_never_bridges_a_join(app):
    # The plain row was removed (e.g. a dropped pending charge). Its key is
    # still indexed, but it has no live row, so neither path joins through it.
    txns = _target(plain_removed=True)
    assert len(_in_memory(txns)) == 2
    assert _indexed(app, txns) == _in_memory(txns)
    with app.app_context():
        assert MerchantGroupKey.query.filter_by(key='in acme widgets').count() == 1


def test_parity_for_the_other_fixtures(app):
    txns = _min_length_corpus() + _hub_corpus()
    assert _indexed(app, txns) == _in_memory(txns)


def _add(txn, n):
    inst_id = db.session.query(Transaction.institution_id).first()[0]
    db.session.add(Transaction(
        plaid_transaction_id=f'late-{n}', institution_id=inst_id,
        account_id=txn.account_id, date=txn.date, description=txn.description,
        merchant_name=txn.merchant_name, merchant_entity_id=txn.merchant_entity_id,
        amount=txn.amount, merchant_key=grouping_key(txn) or None,
    ))
    db.session.commit()


def test_incremental_suffixed_key_joins_the_existing_group(app):
    with app.app_context():
        _persist(_target(suffixed=False))
        update_index()
        db.session.commit()
        groups_before = MerchantGroup.query.count()

        _add(FakeTxn(date(2026, 5, 9), description=SUFFIXED), 1)
        update_index()
        db.session.commit()

        assert MerchantGroup.query.count() == groups_before
        member = MerchantGroupKey.query.filter_by(key='in acme widgets').one()
        suffixed = MerchantGroupKey.query.filter_by(key='in acme widgets anytown usa').one()
        assert suffixed.group_id == member.group_id


def test_an_entity_key_never_joins_through_the_rule(app):
    # Incremental, because a pass handles entity keys before name keys.
    with app.app_context():
        _persist(_target(suffixed=False))
        update_index()
        db.session.commit()

        _add(FakeTxn(date(2026, 5, 9), merchant_name=SUFFIXED,
                     merchant_entity_id='ent-other'), 1)
        update_index()
        db.session.commit()

        member = MerchantGroupKey.query.filter_by(key='in acme widgets').one()
        entity = MerchantGroupKey.query.filter_by(key='entity:ent-other').one()
        assert entity.group_id != member.group_id


def test_version_bump_regroups_an_index_built_without_the_rule(app, monkeypatch):
    """Knowledge 031: the rebuild test must change the real rule, not just the
    number, and assert the output differs."""
    with app.app_context():
        monkeypatch.setattr('app.merchant_groups.member_prefix_match',
                            lambda key, members: None)
        monkeypatch.setattr('app.merchant_groups.GROUPING_ALGO_VERSION', 1)
        _persist(_target())
        update_index()
        db.session.commit()
        before = _partition(grouped_transactions())
        assert _group_of(before, SUFFIXED) != _group_of(before, PLAIN)

        monkeypatch.undo()
        result = update_index()
        db.session.commit()

        assert result['rebuilt'] is True
        after = _partition(grouped_transactions())
        assert _group_of(after, SUFFIXED) == _group_of(after, PLAIN)
        assert len(after) == 1


def test_a_key_whose_rows_were_removed_after_indexing_never_bridges(app):
    # Incremental: the plain row was live when indexed, then Plaid removed it.
    # Its key stays in merchant_group_keys but must no longer act as a member.
    with app.app_context():
        _persist(_target(suffixed=False))
        update_index()
        db.session.commit()
        for t in Transaction.query.filter_by(description=PLAIN, merchant_name=None):
            t.removed = True
        db.session.commit()

        _add(FakeTxn(date(2026, 5, 9), description=SUFFIXED), 1)
        update_index()
        db.session.commit()

        member = MerchantGroupKey.query.filter_by(key='in acme widgets').one()
        suffixed = MerchantGroupKey.query.filter_by(key='in acme widgets anytown usa').one()
        assert suffixed.group_id != member.group_id
