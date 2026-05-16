from datetime import date
from decimal import Decimal
import pytest
from sqlalchemy.exc import IntegrityError
from app.models import Institution, Transaction, SyncLog
from app.models import db


def make_inst():
    return Institution(
        name='Test Bank', slug='test_bank',
        access_token='access-sandbox-xxx', item_id='item-xxx',
    )


def test_institution_defaults(app):
    inst = make_inst()
    db.session.add(inst)
    db.session.commit()
    assert inst.id is not None
    assert inst.status == 'active'
    assert inst.plaid_cursor == ''
    assert inst.last_synced_at is None


def test_transaction_creation(app):
    inst = make_inst()
    db.session.add(inst)
    db.session.flush()
    txn = Transaction(
        plaid_transaction_id='txn-001',
        institution_id=inst.id,
        account_id='acc-001',
        date=date(2026, 5, 1),
        description='Coffee',
        amount=Decimal('5.00'),
    )
    db.session.add(txn)
    db.session.commit()
    assert txn.id is not None
    assert txn.removed is False


def test_cascade_delete_removes_transactions(app):
    inst = make_inst()
    db.session.add(inst)
    db.session.flush()
    txn = Transaction(
        plaid_transaction_id='txn-002', institution_id=inst.id,
        account_id='acc-001', date=date(2026, 5, 1),
        description='Coffee', amount=Decimal('5.00'),
    )
    db.session.add(txn)
    db.session.commit()

    db.session.delete(inst)
    db.session.commit()

    assert Transaction.query.filter_by(plaid_transaction_id='txn-002').first() is None


def test_plaid_transaction_id_unique(app):
    inst = make_inst()
    db.session.add(inst)
    db.session.flush()
    t1 = Transaction(plaid_transaction_id='dup', institution_id=inst.id,
                     account_id='a', date=date(2026, 5, 1), description='A', amount=Decimal('1'))
    t2 = Transaction(plaid_transaction_id='dup', institution_id=inst.id,
                     account_id='a', date=date(2026, 5, 1), description='B', amount=Decimal('1'))
    db.session.add_all([t1, t2])
    with pytest.raises(IntegrityError):
        db.session.commit()


def test_sync_log_creation(app):
    from datetime import datetime, timezone
    inst = make_inst()
    db.session.add(inst)
    db.session.flush()
    log = SyncLog(institution_id=inst.id, started_at=datetime.now(timezone.utc),
                  added_count=5, removed_count=1)
    db.session.add(log)
    db.session.commit()
    assert log.id is not None
    assert log.error is None


def test_institution_slug_unique(app):
    inst1 = Institution(name='Bank A', slug='same_slug', access_token='tok1', item_id='item1')
    inst2 = Institution(name='Bank B', slug='same_slug', access_token='tok2', item_id='item2')
    db.session.add_all([inst1, inst2])
    with pytest.raises(IntegrityError):
        db.session.commit()
