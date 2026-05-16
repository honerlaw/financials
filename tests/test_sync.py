from datetime import date
from decimal import Decimal
from unittest.mock import MagicMock, patch
from app.models import Institution, Transaction, SyncLog
from app.models import db
from app.sync import sync_all_institutions, _upsert_transactions, _mark_removed


def _make_institution(app):
    with app.app_context():
        inst = Institution(
            name='Test Bank', slug='test_bank',
            access_token='access-test', item_id='item-test',
        )
        db.session.add(inst)
        db.session.commit()
        return inst.id


def _mock_txn(txn_id, amount=5.00, txn_date=None):
    txn = MagicMock()
    txn.transaction_id = txn_id
    txn.account_id = 'acc-001'
    txn.date = txn_date or date(2026, 5, 1)
    txn.name = 'Test Merchant'
    txn.merchant_name = 'Test Merchant'
    txn.amount = amount
    txn.personal_finance_category = MagicMock()
    txn.personal_finance_category.primary = 'FOOD_AND_DRINK'
    return txn


def test_upsert_adds_new_transactions(app):
    inst_id = _make_institution(app)
    with app.app_context():
        txns = [_mock_txn('txn-001'), _mock_txn('txn-002')]
        count = _upsert_transactions(inst_id, txns)
        db.session.commit()
        assert count == 2
        assert Transaction.query.count() == 2


def test_upsert_updates_existing_transaction(app):
    inst_id = _make_institution(app)
    with app.app_context():
        _upsert_transactions(inst_id, [_mock_txn('txn-001', amount=5.00)])
        db.session.commit()

        count = _upsert_transactions(inst_id, [_mock_txn('txn-001', amount=6.00)])
        db.session.commit()

        assert count == 0  # no new rows
        stored = Transaction.query.filter_by(plaid_transaction_id='txn-001').first()
        assert stored.amount == Decimal('6.00')


def test_mark_removed_flags_transactions(app):
    inst_id = _make_institution(app)
    with app.app_context():
        _upsert_transactions(inst_id, [_mock_txn('txn-001'), _mock_txn('txn-002')])
        db.session.commit()

        removed = [MagicMock(transaction_id='txn-001')]
        count = _mark_removed(removed)
        db.session.commit()

        assert count == 1
        assert Transaction.query.filter_by(plaid_transaction_id='txn-001').first().removed is True
        assert Transaction.query.filter_by(plaid_transaction_id='txn-002').first().removed is False


@patch('app.sync.PlaidClient')
def test_sync_all_institutions_happy_path(MockPlaidClient, app):
    inst_id = _make_institution(app)
    with app.app_context():
        mock_client = MagicMock()
        mock_client.sync_transactions.return_value = (
            [_mock_txn('txn-new')], [], [], 'new-cursor'
        )
        MockPlaidClient.return_value = mock_client

        sync_all_institutions()

        inst = db.session.get(Institution, inst_id)
        assert inst.plaid_cursor == 'new-cursor'
        assert inst.last_synced_at is not None
        assert inst.status == 'active'
        assert Transaction.query.count() == 1
        log = SyncLog.query.first()
        assert log.added_count == 1
        assert log.error is None


@patch('app.sync.PlaidClient')
def test_sync_sets_login_required_on_error(MockPlaidClient, app):
    import json
    import plaid

    inst_id = _make_institution(app)
    with app.app_context():
        mock_client = MagicMock()
        api_exc = plaid.ApiException(status=400)
        api_exc.body = json.dumps({'error_code': 'ITEM_LOGIN_REQUIRED', 'error_message': 'test'})
        mock_client.sync_transactions.side_effect = api_exc
        MockPlaidClient.return_value = mock_client

        sync_all_institutions()

        inst = db.session.get(Institution, inst_id)
        assert inst.status == 'login_required'
        log = SyncLog.query.first()
        assert log.error is not None
