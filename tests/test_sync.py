from datetime import date
from decimal import Decimal
from unittest.mock import MagicMock, patch
from app.models import Institution, Transaction, SyncLog, Account
from app.models import db
from app.sync import sync_all_institutions, _upsert_transactions, _mark_removed, _upsert_accounts


def _make_institution(app):
    with app.app_context():
        inst = Institution(
            name='Test Bank', slug='test_bank',
            access_token='access-test', item_id='item-test',
        )
        db.session.add(inst)
        db.session.commit()
        return inst.id


def _mock_txn(txn_id, amount=5.00, txn_date=None, **overrides):
    txn = MagicMock()
    txn.transaction_id = txn_id
    txn.account_id = 'acc-001'
    txn.date = txn_date or date(2026, 5, 1)
    txn.authorized_date = None
    txn.name = 'Test Merchant'
    txn.original_description = None
    txn.merchant_name = 'Test Merchant'
    txn.merchant_entity_id = None
    txn.website = None
    txn.amount = amount
    txn.iso_currency_code = 'USD'
    txn.payment_channel = 'in store'
    txn.transaction_code = None
    txn.check_number = None
    txn.account_owner = None
    txn.pending = False
    txn.pending_transaction_id = None
    txn.location = None
    txn.counterparties = None
    txn.personal_finance_category = MagicMock()
    txn.personal_finance_category.primary = 'FOOD_AND_DRINK'
    txn.personal_finance_category.detailed = 'FOOD_AND_DRINK_RESTAURANT'
    txn.personal_finance_category.confidence_level = 'VERY_HIGH'
    for key, value in overrides.items():
        setattr(txn, key, value)
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


def test_upsert_populates_llm_analytical_fields(app):
    inst_id = _make_institution(app)
    with app.app_context():
        counterparties = [{'name': 'Acme Corp', 'type': 'merchant'}]
        location = {'city': 'Brooklyn', 'region': 'NY'}
        txn = _mock_txn(
            'txn-rich',
            authorized_date=date(2026, 4, 30),
            original_description='POS PURCHASE - ACME',
            pending=True,
            payment_channel='online',
            iso_currency_code='USD',
            counterparties=counterparties,
            location=location,
        )
        _upsert_transactions(inst_id, [txn])
        db.session.commit()

        stored = Transaction.query.filter_by(plaid_transaction_id='txn-rich').first()
        assert stored.authorized_date == date(2026, 4, 30)
        assert stored.original_description == 'POS PURCHASE - ACME'
        assert stored.pending is True
        assert stored.payment_channel == 'online'
        assert stored.iso_currency_code == 'USD'
        assert stored.category == 'FOOD_AND_DRINK'
        assert stored.category_detailed == 'FOOD_AND_DRINK_RESTAURANT'
        assert stored.category_confidence == 'VERY_HIGH'
        assert stored.counterparties == counterparties
        assert stored.location == location


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
            [_mock_txn('txn-new')], [], [], 'new-cursor', [],
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


def _mock_account(account_id='acc-001', name='Sapphire', mask='1234',
                  type_='credit', subtype='credit card',
                  current=125.50, available=874.50):
    acct = MagicMock()
    acct.account_id = account_id
    acct.name = name
    acct.official_name = f'{name} (Official)'
    acct.mask = mask
    type_mock = MagicMock()
    type_mock.value = type_
    acct.type = type_mock
    subtype_mock = MagicMock()
    subtype_mock.value = subtype
    acct.subtype = subtype_mock
    balances = MagicMock()
    balances.current = current
    balances.available = available
    balances.iso_currency_code = 'USD'
    acct.balances = balances
    return acct


def test_upsert_accounts_inserts_new_rows(app):
    inst_id = _make_institution(app)
    with app.app_context():
        _upsert_accounts(inst_id, [_mock_account('acc-001'), _mock_account('acc-002', name='Freedom')])
        db.session.commit()

        rows = Account.query.order_by(Account.plaid_account_id).all()
        assert [a.plaid_account_id for a in rows] == ['acc-001', 'acc-002']
        first = rows[0]
        assert first.institution_id == inst_id
        assert first.name == 'Sapphire'
        assert first.mask == '1234'
        assert first.type == 'credit'
        assert first.subtype == 'credit card'
        assert first.current_balance == Decimal('125.50')
        assert first.available_balance == Decimal('874.50')
        assert first.iso_currency_code == 'USD'
        assert first.last_synced_at is not None


def test_upsert_accounts_updates_balances_on_second_call(app):
    inst_id = _make_institution(app)
    with app.app_context():
        _upsert_accounts(inst_id, [_mock_account('acc-001', current=125.50)])
        db.session.commit()

        _upsert_accounts(inst_id, [_mock_account('acc-001', current=200.00, name='Sapphire Reserve')])
        db.session.commit()

        assert Account.query.count() == 1
        row = Account.query.filter_by(plaid_account_id='acc-001').first()
        assert row.current_balance == Decimal('200.00')
        assert row.name == 'Sapphire Reserve'


@patch('app.sync.PlaidClient')
def test_sync_all_institutions_persists_accounts(MockPlaidClient, app):
    inst_id = _make_institution(app)
    with app.app_context():
        mock_client = MagicMock()
        mock_client.sync_transactions.return_value = (
            [_mock_txn('txn-new')], [], [], 'cursor-x',
            [_mock_account('acc-001'), _mock_account('acc-002', name='Freedom')],
        )
        MockPlaidClient.return_value = mock_client

        sync_all_institutions()

        assert Account.query.count() == 2


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
