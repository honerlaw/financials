from datetime import date
from decimal import Decimal
from unittest.mock import MagicMock, patch

import pytest
from freezegun import freeze_time
from app.models import Institution, Transaction, SyncLog, Account
from app.models import db
from app.sync import (
    sync_all_institutions, run_daily_sync, _upsert_transactions, _mark_removed,
    _upsert_accounts, _refresh_balances, _refresh_liabilities,
    _refresh_investments,
)


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
        mock_client.get_balances.return_value = []
        mock_client.get_investments.return_value = ([], [])
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
        mock_client.get_balances.return_value = []
        mock_client.get_investments.return_value = ([], [])
        MockPlaidClient.return_value = mock_client

        sync_all_institutions()

        assert Account.query.count() == 2


@patch('app.sync.PlaidClient')
def test_sync_refreshes_balances_via_balance_endpoint(MockPlaidClient, app):
    inst_id = _make_institution(app)
    with app.app_context():
        mock_client = MagicMock()
        # piggyback returns a stale snapshot
        mock_client.sync_transactions.return_value = (
            [], [], [], 'cursor-x',
            [_mock_account('acc-001', current=100.00, available=900.00)],
        )
        # /accounts/balance/get returns the authoritative live values
        mock_client.get_balances.return_value = [
            _mock_account('acc-001', current=150.75, available=849.25),
        ]
        mock_client.get_investments.return_value = ([], [])
        MockPlaidClient.return_value = mock_client

        sync_all_institutions()

        row = Account.query.filter_by(plaid_account_id='acc-001').first()
        assert row.current_balance == Decimal('150.75')
        assert row.available_balance == Decimal('849.25')
        log = SyncLog.query.first()
        assert log.error is None
        assert mock_client.get_balances.call_count == 1


@patch('app.sync.PlaidClient')
def test_sync_handles_balance_endpoint_error(MockPlaidClient, app):
    import json
    import plaid

    inst_id = _make_institution(app)
    with app.app_context():
        mock_client = MagicMock()
        mock_client.sync_transactions.return_value = (
            [_mock_txn('txn-new')], [], [], 'cursor-x',
            [_mock_account('acc-001', current=100.00)],
        )
        # Balance refresh blows up — sync should not abort.
        api_exc = plaid.ApiException(status=429)
        api_exc.body = json.dumps({'error_code': 'RATE_LIMIT_EXCEEDED', 'error_message': 'slow down'})
        mock_client.get_balances.side_effect = api_exc
        mock_client.get_investments.return_value = ([], [])
        MockPlaidClient.return_value = mock_client

        sync_all_institutions()

        # The transaction still landed and the piggyback balance still applied.
        assert Transaction.query.count() == 1
        row = Account.query.filter_by(plaid_account_id='acc-001').first()
        assert row.current_balance == Decimal('100.00')
        # The error is recorded on the SyncLog.
        log = SyncLog.query.first()
        assert log.error is not None
        assert 'RATE_LIMIT_EXCEEDED' in log.error
        assert 'balance refresh failed' in log.error
        # Institution remains active — balance failures are non-fatal.
        inst = db.session.get(Institution, inst_id)
        assert inst.status == 'active'


def _mock_credit_liability(account_id='acc-001', due_date=None,
                           statement=250.00, minimum=35.00):
    entry = MagicMock()
    entry.account_id = account_id
    entry.next_payment_due_date = due_date if due_date is not None else date(2026, 8, 1)
    entry.last_statement_balance = statement
    entry.minimum_payment_amount = minimum
    return entry


def _mock_liabilities(credit=None, student=None, mortgage=None):
    liab = MagicMock()
    liab.credit = credit or []
    liab.student = student or []
    liab.mortgage = mortgage or []
    return liab


@patch('app.sync.PlaidClient')
def test_sync_populates_liability_fields(MockPlaidClient, app):
    inst_id = _make_institution(app)
    with app.app_context():
        mock_client = MagicMock()
        mock_client.sync_transactions.return_value = (
            [], [], [], 'cursor-x', [_mock_account('acc-001')],
        )
        mock_client.get_balances.return_value = []
        mock_client.get_liabilities.return_value = _mock_liabilities(
            credit=[_mock_credit_liability('acc-001', due_date=date(2026, 8, 15),
                                           statement=432.10, minimum=35.00)]
        )
        mock_client.get_investments.return_value = ([], [])
        MockPlaidClient.return_value = mock_client

        sync_all_institutions()

        row = Account.query.filter_by(plaid_account_id='acc-001').first()
        assert row.next_payment_due_date == date(2026, 8, 15)
        assert row.last_statement_balance == Decimal('432.10')
        assert row.minimum_payment_amount == Decimal('35.00')
        log = SyncLog.query.first()
        assert log.error is None


def test_refresh_liabilities_uses_next_monthly_payment_for_mortgage(app):
    inst_id = _make_institution(app)
    with app.app_context():
        _upsert_accounts(inst_id, [_mock_account('acc-mtg', type_='loan', subtype='mortgage')])
        db.session.commit()

        mortgage = MagicMock()
        mortgage.account_id = 'acc-mtg'
        mortgage.next_payment_due_date = date(2026, 9, 1)
        # Mortgages have no minimum_payment_amount — the amount owed lives on
        # next_monthly_payment, which _refresh_liabilities falls back to.
        mortgage.minimum_payment_amount = None
        mortgage.next_monthly_payment = 1500.00

        client = MagicMock()
        client.get_liabilities.return_value = _mock_liabilities(mortgage=[mortgage])
        inst = db.session.get(Institution, inst_id)
        err = _refresh_liabilities(client, inst)
        db.session.commit()

        assert err is None
        row = Account.query.filter_by(plaid_account_id='acc-mtg').first()
        assert row.next_payment_due_date == date(2026, 9, 1)
        assert row.minimum_payment_amount == Decimal('1500.00')


@patch('app.sync.PlaidClient')
def test_sync_ignores_benign_liability_error(MockPlaidClient, app):
    """PRODUCTS_NOT_SUPPORTED (depository-only / non-consented Item) is normal."""
    import json
    import plaid

    inst_id = _make_institution(app)
    with app.app_context():
        mock_client = MagicMock()
        mock_client.sync_transactions.return_value = (
            [_mock_txn('txn-new')], [], [], 'cursor-x', [_mock_account('acc-001')],
        )
        mock_client.get_balances.return_value = []
        api_exc = plaid.ApiException(status=400)
        api_exc.body = json.dumps(
            {'error_code': 'PRODUCTS_NOT_SUPPORTED', 'error_message': 'no liabilities'}
        )
        mock_client.get_liabilities.side_effect = api_exc
        mock_client.get_investments.return_value = ([], [])
        MockPlaidClient.return_value = mock_client

        sync_all_institutions()

        log = SyncLog.query.first()
        assert log.error is None  # benign — not annotated
        inst = db.session.get(Institution, inst_id)
        assert inst.status == 'active'


@patch('app.sync.PlaidClient')
def test_sync_ignores_additional_consent_required(MockPlaidClient, app):
    """An Item linked before the `liabilities` consent must not spam the log.

    Plaid returns ADDITIONAL_CONSENT_REQUIRED for every such Item on every
    sync; annotating the SyncLog for it would bury real errors in noise. The
    user clears it by re-connecting (update mode requests the consent).
    """
    import json
    import plaid

    inst_id = _make_institution(app)
    with app.app_context():
        mock_client = MagicMock()
        mock_client.sync_transactions.return_value = (
            [_mock_txn('txn-new')], [], [], 'cursor-x', [_mock_account('acc-001')],
        )
        mock_client.get_balances.return_value = []
        api_exc = plaid.ApiException(status=400)
        api_exc.body = json.dumps({
            'error_code': 'ADDITIONAL_CONSENT_REQUIRED',
            'error_message': 'consent required for liabilities',
        })
        mock_client.get_liabilities.side_effect = api_exc
        mock_client.get_investments.return_value = ([], [])
        MockPlaidClient.return_value = mock_client

        sync_all_institutions()

        log = SyncLog.query.first()
        assert log.error is None  # benign — not annotated
        assert Transaction.query.count() == 1  # sync did not abort
        inst = db.session.get(Institution, inst_id)
        assert inst.status == 'active'


@patch('app.sync.PlaidClient')
def test_sync_logs_unexpected_liability_error(MockPlaidClient, app):
    """An unexpected liabilities failure is recorded on the SyncLog, non-fatally."""
    import json
    import plaid

    inst_id = _make_institution(app)
    with app.app_context():
        mock_client = MagicMock()
        mock_client.sync_transactions.return_value = (
            [_mock_txn('txn-new')], [], [], 'cursor-x', [_mock_account('acc-001')],
        )
        mock_client.get_balances.return_value = []
        api_exc = plaid.ApiException(status=429)
        api_exc.body = json.dumps(
            {'error_code': 'RATE_LIMIT_EXCEEDED', 'error_message': 'slow down'}
        )
        mock_client.get_liabilities.side_effect = api_exc
        mock_client.get_investments.return_value = ([], [])
        MockPlaidClient.return_value = mock_client

        sync_all_institutions()

        assert Transaction.query.count() == 1  # sync did not abort
        log = SyncLog.query.first()
        assert log.error is not None
        assert 'liability refresh failed' in log.error
        assert 'RATE_LIMIT_EXCEEDED' in log.error
        inst = db.session.get(Institution, inst_id)
        assert inst.status == 'active'


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
        mock_client.get_investments.return_value = ([], [])
        MockPlaidClient.return_value = mock_client

        sync_all_institutions()

        inst = db.session.get(Institution, inst_id)
        assert inst.status == 'login_required'
        log = SyncLog.query.first()
        assert log.error is not None


@patch('app.sync.PlaidClient')
def test_daily_sync_dispatches_digest(MockPlaidClient, app):
    """run_daily_sync fires the digest hook after syncing."""
    MockPlaidClient.return_value = MagicMock()
    with app.app_context():
        with patch('app.notifications.send_daily_digest') as mock_send:
            run_daily_sync()
            assert mock_send.called


@patch('app.sync.PlaidClient')
def test_page_load_sync_does_not_text(MockPlaidClient, app):
    """The shared sync path (/api/sync on every page load) must never notify.

    This is what makes the digest land at 7am rather than whenever the dashboard
    is next opened.
    """
    MockPlaidClient.return_value = MagicMock()
    with app.app_context():
        with patch('app.notifications.send_daily_digest') as mock_send:
            sync_all_institutions()
            assert not mock_send.called


@patch('app.sync.PlaidClient')
def test_daily_sync_uses_local_today_not_utc(MockPlaidClient, app):
    """The digest's "today" comes from APP_TIMEZONE, not the container's UTC."""
    MockPlaidClient.return_value = MagicMock()
    with app.app_context():
        app.config['APP_TIMEZONE'] = 'America/New_York'
        with freeze_time('2026-08-09 03:30:00'):  # 11:30pm Aug 8 in New York
            with patch('app.notifications.send_daily_digest') as mock_send:
                run_daily_sync()
        assert mock_send.call_args[0][1] == date(2026, 8, 8)


@patch('app.sync.PlaidClient')
def test_daily_sync_survives_digest_failure(MockPlaidClient, app):
    """A notifier exception must not abort the sync (non-fatal contract)."""
    MockPlaidClient.return_value = MagicMock()
    with app.app_context():
        with patch('app.notifications.send_daily_digest',
                   side_effect=RuntimeError('boom')):
            # Should not raise.
            run_daily_sync()


@patch('app.sync.PlaidClient')
def test_daily_sync_survives_digest_import_failure(MockPlaidClient, app):
    """An import-time failure in the notifier path must not abort the sync."""
    import sys
    MockPlaidClient.return_value = MagicMock()
    with app.app_context():
        # Poisoning sys.modules makes `from app.notifications import ...` raise.
        with patch.dict(sys.modules, {'app.notifications': None}):
            run_daily_sync()  # should not raise


def _mock_holding(account_id='acc-inv', institution_value=1000.00,
                  vested_value=600.00, vested_quantity=None,
                  institution_price=None):
    holding = MagicMock()
    holding.account_id = account_id
    holding.institution_value = institution_value
    holding.vested_value = vested_value
    holding.vested_quantity = vested_quantity
    holding.institution_price = institution_price
    return holding


@patch('app.sync.PlaidClient')
def test_sync_populates_vested_fields(MockPlaidClient, app):
    inst_id = _make_institution(app)
    with app.app_context():
        mock_client = MagicMock()
        mock_client.sync_transactions.return_value = (
            [], [], [], 'cursor-x',
            [_mock_account('acc-inv', type_='investment', subtype='brokerage')],
        )
        mock_client.get_balances.return_value = []
        mock_client.get_liabilities.return_value = None
        # Two equity-comp lots on one account: totals are summed.
        mock_client.get_investments.return_value = ([], [
            _mock_holding('acc-inv', institution_value=1000.00, vested_value=600.00),
            _mock_holding('acc-inv', institution_value=500.00, vested_value=125.00),
        ])
        MockPlaidClient.return_value = mock_client

        sync_all_institutions()

        row = Account.query.filter_by(plaid_account_id='acc-inv').first()
        assert row.vested_value == Decimal('725.00')
        assert row.unvested_value == Decimal('775.00')
        log = SyncLog.query.first()
        assert log.error is None


def test_refresh_investments_derives_vested_from_quantity(app):
    """An institution reporting only vested_quantity is priced at institution_price."""
    inst_id = _make_institution(app)
    with app.app_context():
        _upsert_accounts(inst_id, [_mock_account('acc-inv', type_='investment',
                                                 subtype='brokerage')])
        db.session.commit()

        client = MagicMock()
        client.get_investments.return_value = ([], [
            _mock_holding('acc-inv', institution_value=1000.00, vested_value=None,
                          vested_quantity=40, institution_price=10.00),
        ])
        inst = db.session.get(Institution, inst_id)
        err = _refresh_investments(client, inst)
        db.session.commit()

        assert err is None
        row = Account.query.filter_by(plaid_account_id='acc-inv').first()
        assert row.vested_value == Decimal('400.00')
        assert row.unvested_value == Decimal('600.00')


def test_refresh_investments_rounds_derived_value_to_cents(app):
    """The derived quantity x price product is stored at Numeric(12, 2) precision."""
    inst_id = _make_institution(app)
    with app.app_context():
        _upsert_accounts(inst_id, [_mock_account('acc-inv', type_='investment',
                                                 subtype='brokerage')])
        db.session.commit()

        client = MagicMock()
        client.get_investments.return_value = ([], [
            _mock_holding('acc-inv', institution_value=1000.00, vested_value=None,
                          vested_quantity=33.333, institution_price=12.34),
        ])
        inst = db.session.get(Institution, inst_id)
        err = _refresh_investments(client, inst)
        db.session.commit()

        assert err is None
        row = Account.query.filter_by(plaid_account_id='acc-inv').first()
        # 33.333 * 12.34 == 411.32922 -> 411.33
        assert row.vested_value == Decimal('411.33')
        assert row.unvested_value == Decimal('588.67')


def test_refresh_investments_ignores_holdings_with_no_vested_figure(app):
    """A plain brokerage position is not unvested — it is excluded entirely."""
    inst_id = _make_institution(app)
    with app.app_context():
        _upsert_accounts(inst_id, [_mock_account('acc-inv', type_='investment',
                                                 subtype='brokerage')])
        db.session.commit()

        client = MagicMock()
        client.get_investments.return_value = ([], [
            _mock_holding('acc-inv', institution_value=5000.00, vested_value=None,
                          vested_quantity=None, institution_price=None),
        ])
        inst = db.session.get(Institution, inst_id)
        err = _refresh_investments(client, inst)
        db.session.commit()

        assert err is None
        row = Account.query.filter_by(plaid_account_id='acc-inv').first()
        assert row.vested_value is None
        assert row.unvested_value is None


def test_refresh_investments_clamps_negative_unvested(app):
    """A stale institution_price must not produce a negative unvested amount."""
    inst_id = _make_institution(app)
    with app.app_context():
        _upsert_accounts(inst_id, [_mock_account('acc-inv', type_='investment',
                                                 subtype='brokerage')])
        db.session.commit()

        client = MagicMock()
        client.get_investments.return_value = ([], [
            _mock_holding('acc-inv', institution_value=100.00, vested_value=150.00),
        ])
        inst = db.session.get(Institution, inst_id)
        err = _refresh_investments(client, inst)
        db.session.commit()

        assert err is None
        row = Account.query.filter_by(plaid_account_id='acc-inv').first()
        assert row.vested_value == Decimal('150.00')
        assert row.unvested_value == Decimal('0')


@pytest.mark.parametrize('error_code', [
    'ADDITIONAL_CONSENT_REQUIRED',
    'PRODUCTS_NOT_SUPPORTED',
    'NO_INVESTMENT_ACCOUNTS',
    'NO_ACCOUNTS',
])
@patch('app.sync.PlaidClient')
def test_sync_ignores_benign_investment_error(MockPlaidClient, app, error_code):
    """A never-consented or investment-free Item must not spam the SyncLog."""
    import json
    import plaid

    inst_id = _make_institution(app)
    with app.app_context():
        mock_client = MagicMock()
        mock_client.sync_transactions.return_value = (
            [_mock_txn('txn-new')], [], [], 'cursor-x', [_mock_account('acc-001')],
        )
        mock_client.get_balances.return_value = []
        mock_client.get_liabilities.return_value = None
        api_exc = plaid.ApiException(status=400)
        api_exc.body = json.dumps({
            'error_code': error_code, 'error_message': 'no investments',
        })
        mock_client.get_investments.side_effect = api_exc
        MockPlaidClient.return_value = mock_client

        sync_all_institutions()

        log = SyncLog.query.first()
        assert log.error is None  # benign — not annotated
        assert Transaction.query.count() == 1  # sync did not abort
        inst = db.session.get(Institution, inst_id)
        assert inst.status == 'active'


@patch('app.sync.PlaidClient')
def test_sync_logs_unexpected_investment_error(MockPlaidClient, app):
    """An unexpected holdings failure is recorded on the SyncLog, non-fatally."""
    import json
    import plaid

    inst_id = _make_institution(app)
    with app.app_context():
        mock_client = MagicMock()
        mock_client.sync_transactions.return_value = (
            [_mock_txn('txn-new')], [], [], 'cursor-x', [_mock_account('acc-001')],
        )
        mock_client.get_balances.return_value = []
        mock_client.get_liabilities.return_value = None
        api_exc = plaid.ApiException(status=429)
        api_exc.body = json.dumps(
            {'error_code': 'RATE_LIMIT_EXCEEDED', 'error_message': 'slow down'}
        )
        mock_client.get_investments.side_effect = api_exc
        MockPlaidClient.return_value = mock_client

        sync_all_institutions()

        assert Transaction.query.count() == 1  # sync did not abort
        log = SyncLog.query.first()
        assert log.error is not None
        assert 'investment refresh failed' in log.error
        assert 'RATE_LIMIT_EXCEEDED' in log.error
        inst = db.session.get(Institution, inst_id)
        assert inst.status == 'active'


# ── Accounts transactions/sync never returns ──────────────────────────────────
#
# An investment-only Item (the linked E*TRADE stock plan) has no
# transactions-covered accounts, so transactions/sync returns an empty accounts
# array and the piggyback creates nothing. Before unit 021 the dedicated
# refreshes all skipped the unknown account, so it never got a row and never
# rendered a dashboard card.


@patch('app.sync.PlaidClient')
def test_sync_creates_account_seen_only_in_balance_payload(MockPlaidClient, app):
    """accounts/balance/get returns every account on the Item — create the row."""
    inst_id = _make_institution(app)
    with app.app_context():
        mock_client = MagicMock()
        mock_client.sync_transactions.return_value = ([], [], [], 'cursor-x', [])
        mock_client.get_balances.return_value = [
            _mock_account('acc-etrade', name='Stock Plan', mask='9999',
                          type_='investment', subtype='stock plan',
                          current=42000.00, available=None),
        ]
        mock_client.get_liabilities.return_value = None
        mock_client.get_investments.return_value = ([], [])
        MockPlaidClient.return_value = mock_client

        sync_all_institutions()

        row = Account.query.filter_by(plaid_account_id='acc-etrade').first()
        assert row is not None
        assert row.institution_id == inst_id
        assert row.name == 'Stock Plan'
        assert row.mask == '9999'
        assert row.type == 'investment'
        assert row.subtype == 'stock plan'
        assert row.current_balance == Decimal('42000.00')
        log = SyncLog.query.first()
        assert log.error is None


@patch('app.sync.PlaidClient')
def test_sync_creates_account_seen_only_in_holdings_payload(MockPlaidClient, app):
    """The holdings response's accounts array is the guaranteed investment source."""
    inst_id = _make_institution(app)
    with app.app_context():
        mock_client = MagicMock()
        mock_client.sync_transactions.return_value = ([], [], [], 'cursor-x', [])
        # Neither the piggyback nor balance/get surfaces it.
        mock_client.get_balances.return_value = []
        mock_client.get_liabilities.return_value = None
        mock_client.get_investments.return_value = (
            [_mock_account('acc-etrade', name='Stock Plan', mask='9999',
                           type_='investment', subtype='stock plan',
                           current=42000.00, available=None)],
            [_mock_holding('acc-etrade', institution_value=42000.00,
                           vested_value=18000.00)],
        )
        MockPlaidClient.return_value = mock_client

        sync_all_institutions()

        row = Account.query.filter_by(plaid_account_id='acc-etrade').first()
        assert row is not None
        assert row.institution_id == inst_id
        assert row.name == 'Stock Plan'
        # The row exists, so the vested figures now land instead of being dropped.
        assert row.vested_value == Decimal('18000.00')
        assert row.unvested_value == Decimal('24000.00')


@patch('app.sync.PlaidClient')
def test_sync_creates_investment_account_with_no_holdings(MockPlaidClient, app):
    """The accounts upsert runs before the empty-holdings early return."""
    _make_institution(app)
    with app.app_context():
        mock_client = MagicMock()
        mock_client.sync_transactions.return_value = ([], [], [], 'cursor-x', [])
        mock_client.get_balances.return_value = []
        mock_client.get_liabilities.return_value = None
        mock_client.get_investments.return_value = (
            [_mock_account('acc-empty', name='Brokerage', type_='investment',
                           subtype='brokerage')],
            [],
        )
        MockPlaidClient.return_value = mock_client

        sync_all_institutions()

        row = Account.query.filter_by(plaid_account_id='acc-empty').first()
        assert row is not None
        assert row.vested_value is None
        assert row.unvested_value is None


def test_refresh_balances_leaves_metadata_alone_for_known_accounts(app):
    """Create-only: an existing row still takes the balance-only update path."""
    inst_id = _make_institution(app)
    with app.app_context():
        _upsert_accounts(inst_id, [_mock_account('acc-001', name='Piggyback Name',
                                                 mask='1111')])
        db.session.commit()

        client = MagicMock()
        client.get_balances.return_value = [
            _mock_account('acc-001', name='Balance Endpoint Name', mask='2222',
                          current=99.00, available=88.00),
        ]
        inst = db.session.get(Institution, inst_id)
        err = _refresh_balances(client, inst)
        db.session.commit()

        assert err is None
        row = Account.query.filter_by(plaid_account_id='acc-001').first()
        # Balances refreshed…
        assert row.current_balance == Decimal('99.00')
        assert row.available_balance == Decimal('88.00')
        # …metadata still owned by the transactions/sync piggyback.
        assert row.name == 'Piggyback Name'
        assert row.mask == '1111'
        assert Account.query.count() == 1


def test_refresh_balances_preserves_currency_when_payload_omits_it(app):
    """iso_currency_code is only written when non-null.

    Plaid nulls iso_currency_code whenever unofficial_currency_code is
    populated, so an unconditional write would clobber a known code.
    """
    inst_id = _make_institution(app)
    with app.app_context():
        _upsert_accounts(inst_id, [_mock_account('acc-001')])
        db.session.commit()

        acct = _mock_account('acc-001', current=10.00, available=5.00)
        acct.balances.iso_currency_code = None
        client = MagicMock()
        client.get_balances.return_value = [acct]
        inst = db.session.get(Institution, inst_id)
        _refresh_balances(client, inst)
        db.session.commit()

        row = Account.query.filter_by(plaid_account_id='acc-001').first()
        assert row.iso_currency_code == 'USD'
        assert row.current_balance == Decimal('10.00')


def test_refresh_balances_skips_known_account_with_no_balances(app):
    """A payload with no balances object must not null a known balance."""
    inst_id = _make_institution(app)
    with app.app_context():
        _upsert_accounts(inst_id, [_mock_account('acc-001', current=500.00)])
        db.session.commit()

        acct = _mock_account('acc-001')
        acct.balances = None
        client = MagicMock()
        client.get_balances.return_value = [acct]
        inst = db.session.get(Institution, inst_id)
        _refresh_balances(client, inst)
        db.session.commit()

        row = Account.query.filter_by(plaid_account_id='acc-001').first()
        assert row.current_balance == Decimal('500.00')
