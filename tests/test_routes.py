from datetime import date
from decimal import Decimal
from unittest.mock import MagicMock, patch
from app.models import Institution, Transaction, SyncLog
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


def test_sync_status_returns_json(auth_client):
    res = auth_client.get('/api/sync/status')
    assert res.status_code == 200
    data = res.json
    assert 'last_sync' in data
    assert 'institutions' in data
