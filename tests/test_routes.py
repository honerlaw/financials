from datetime import date
from decimal import Decimal
from unittest.mock import MagicMock, patch
from app.models import Institution, Transaction, SyncLog, Account
from app.models import db


def _make_institution(app, name='Test Bank', slug='test_bank'):
    with app.app_context():
        inst = Institution(
            name=name, slug=slug,
            access_token='access-test', item_id=f'item-{slug}',
        )
        db.session.add(inst)
        db.session.commit()
        return inst.id


def _make_transaction(app, inst_id, plaid_id='txn-001', description='Starbucks'):
    with app.app_context():
        txn = Transaction(
            plaid_transaction_id=plaid_id,
            institution_id=inst_id,
            account_id='acc-001',
            date=date(2026, 5, 1),
            description=description,
            amount=Decimal('6.75'),
        )
        db.session.add(txn)
        db.session.commit()


def test_index_shows_transactions(auth_client, app):
    inst_id = _make_institution(app)
    _make_transaction(app, inst_id)
    res = auth_client.get('/')
    assert res.status_code == 200
    assert b'Starbucks' in res.data


def test_index_filters_by_institution(auth_client, app):
    inst_id = _make_institution(app)
    inst2_id = _make_institution(app, name='Citi', slug='citi')
    _make_transaction(app, inst_id, 'txn-a', 'AmEx Charge')
    _make_transaction(app, inst2_id, 'txn-b', 'Citi Charge')

    res = auth_client.get(f'/?institution={inst_id}')
    assert b'AmEx Charge' in res.data
    assert b'Citi Charge' not in res.data


def test_settings_shows_institutions(auth_client, app):
    _make_institution(app)
    res = auth_client.get('/settings')
    assert res.status_code == 200
    assert b'Test Bank' in res.data


@patch('app.plaid_client.PlaidClient')
def test_create_link_token(MockPlaidClient, auth_client):
    MockPlaidClient.return_value.create_link_token.return_value = 'link-test-token'
    res = auth_client.post('/api/plaid/create_link_token')
    assert res.status_code == 200
    assert res.json['link_token'] == 'link-test-token'


@patch('app.plaid_client.PlaidClient')
def test_exchange_token_creates_institution(MockPlaidClient, auth_client, app):
    MockPlaidClient.return_value.exchange_token.return_value = (
        'access-sandbox-abc', 'item-123', 'American Express', 'american_express'
    )
    res = auth_client.post('/api/plaid/exchange_token',
                           json={'public_token': 'public-test'})
    assert res.status_code == 200
    assert res.json['name'] == 'American Express'

    with app.app_context():
        assert Institution.query.filter_by(slug='american_express').first() is not None


@patch('app.plaid_client.PlaidClient')
def test_exchange_token_rejects_duplicate(MockPlaidClient, auth_client, app):
    _make_institution(app, name='Test Bank', slug='test_bank')
    MockPlaidClient.return_value.exchange_token.return_value = (
        'tok', 'item', 'Test Bank', 'test_bank'
    )
    res = auth_client.post('/api/plaid/exchange_token',
                           json={'public_token': 'pt'})
    assert res.status_code == 400
    assert 'already connected' in res.json['error']


@patch('app.plaid_client.PlaidClient')
def test_remove_institution_deletes_it(MockPlaidClient, auth_client, app):
    inst_id = _make_institution(app)
    res = auth_client.post(f'/api/plaid/remove/{inst_id}')
    assert res.status_code == 200
    with app.app_context():
        assert db.session.get(Institution, inst_id) is None


def _make_account(app, inst_id, plaid_account_id='acc-001', name='Sapphire', mask='1234'):
    with app.app_context():
        acct = Account(
            institution_id=inst_id,
            plaid_account_id=plaid_account_id,
            name=name,
            mask=mask,
            type='credit',
            subtype='credit card',
        )
        db.session.add(acct)
        db.session.commit()
        return acct.id


def _make_txn_row(app, inst_id, plaid_account_id, plaid_id, amount, txn_date):
    with app.app_context():
        db.session.add(Transaction(
            plaid_transaction_id=plaid_id,
            institution_id=inst_id,
            account_id=plaid_account_id,
            date=txn_date,
            description='X',
            amount=Decimal(str(amount)),
        ))
        db.session.commit()


def test_index_navbar_has_transactions_link(auth_client, app):
    res = auth_client.get('/')
    assert res.status_code == 200
    assert b'>Transactions<' in res.data
    assert b'href="/chat"' in res.data


def test_index_account_totals_aggregate_by_account(auth_client, app):
    inst_id = _make_institution(app, name='AmEx', slug='amex')
    _make_account(app, inst_id, plaid_account_id='acc-001', name='Platinum', mask='1111')
    _make_account(app, inst_id, plaid_account_id='acc-002', name='Gold', mask='2222')
    _make_txn_row(app, inst_id, 'acc-001', 'p-1', '10.00', date(2026, 5, 1))
    _make_txn_row(app, inst_id, 'acc-001', 'p-2', '15.50', date(2026, 5, 2))
    _make_txn_row(app, inst_id, 'acc-002', 'g-1', '-5.00', date(2026, 5, 3))

    res = auth_client.get('/')
    assert res.status_code == 200
    # Card strip shows both accounts with their masks and totals.
    assert b'Platinum' in res.data
    assert b'1111' in res.data
    assert b'Gold' in res.data
    assert b'2222' in res.data
    assert b'-$25.50' in res.data  # Platinum total (positive sums shown as outflow with leading -)
    assert b'+$5.00' in res.data   # Gold total (refund shown as inflow)


def test_index_account_totals_respect_month_filter(auth_client, app):
    inst_id = _make_institution(app, name='Citi', slug='citi')
    _make_account(app, inst_id, plaid_account_id='acc-c1', name='Double Cash', mask='9999')
    _make_txn_row(app, inst_id, 'acc-c1', 'in-month', '10.00', date(2026, 5, 15))
    _make_txn_row(app, inst_id, 'acc-c1', 'out-of-month', '99.00', date(2026, 4, 15))

    res = auth_client.get('/?month=2026-05')
    assert res.status_code == 200
    assert b'-$10.00' in res.data
    assert b'$99.00' not in res.data


def test_index_account_totals_hide_other_institutions_when_filtered(auth_client, app):
    amex_id = _make_institution(app, name='AmEx', slug='amex')
    citi_id = _make_institution(app, name='Citi', slug='citi')
    _make_account(app, amex_id, plaid_account_id='acc-a', name='Platinum')
    _make_account(app, citi_id, plaid_account_id='acc-c', name='Double Cash')
    _make_txn_row(app, amex_id, 'acc-a', 'a-1', '10.00', date(2026, 5, 1))
    _make_txn_row(app, citi_id, 'acc-c', 'c-1', '20.00', date(2026, 5, 1))

    res = auth_client.get(f'/?institution={amex_id}')
    assert res.status_code == 200
    assert b'Platinum' in res.data
    assert b'Double Cash' not in res.data


def test_sync_status_returns_json(auth_client):
    res = auth_client.get('/api/sync/status')
    assert res.status_code == 200
    data = res.json
    assert 'last_sync' in data
    assert 'institutions' in data
