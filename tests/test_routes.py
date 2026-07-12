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


# ── Reconnect banner + update-mode reconnect ───────────────────────────────────

def _make_login_required_institution(app, name='Test Bank', slug='test_bank'):
    with app.app_context():
        inst = Institution(
            name=name, slug=slug,
            access_token='access-test', item_id=f'item-{slug}',
            status='login_required',
        )
        db.session.add(inst)
        db.session.commit()
        return inst.id


def test_banner_shows_when_login_required(auth_client, app):
    _make_login_required_institution(app, name='Truist Bank', slug='truist')
    res = auth_client.get('/')
    assert res.status_code == 200
    assert b'Reconnection needed' in res.data
    assert b'Reconnect Truist Bank' in res.data


def test_banner_absent_when_all_active(auth_client, app):
    _make_institution(app, name='Active Bank', slug='active_bank')  # status defaults to 'active'
    res = auth_client.get('/')
    assert res.status_code == 200
    assert b'Reconnection needed' not in res.data


def test_banner_absent_when_unauthenticated(client, app):
    # Unauthenticated request redirects to login; no DB-driven banner served.
    _make_login_required_institution(app)
    res = client.get('/', follow_redirects=True)
    assert b'Reconnection needed' not in res.data


@patch('app.plaid_client.PlaidClient')
def test_update_link_token_returns_token(MockPlaidClient, auth_client, app):
    inst_id = _make_login_required_institution(app)
    MockPlaidClient.return_value.create_update_link_token.return_value = 'link-update-abc'
    res = auth_client.post(f'/api/plaid/update_link_token/{inst_id}')
    assert res.status_code == 200
    assert res.json['link_token'] == 'link-update-abc'
    # Built from the institution's stored access token.
    MockPlaidClient.return_value.create_update_link_token.assert_called_once_with('access-test')


def test_update_link_token_404_for_missing(auth_client):
    res = auth_client.post('/api/plaid/update_link_token/99999')
    assert res.status_code == 404


def test_update_link_token_requires_auth(client, app):
    inst_id = _make_login_required_institution(app)
    res = client.post(f'/api/plaid/update_link_token/{inst_id}')
    assert res.status_code == 302  # redirect to login, not a 200 with a token


@patch('app.sync.sync_all_institutions')
def test_reconnect_sets_status_active(mock_sync, auth_client, app):
    inst_id = _make_login_required_institution(app)
    res = auth_client.post(f'/api/plaid/reconnect/{inst_id}')
    assert res.status_code == 200
    assert res.json['status'] == 'ok'
    with app.app_context():
        assert db.session.get(Institution, inst_id).status == 'active'


def test_reconnect_404_for_missing(auth_client):
    res = auth_client.post('/api/plaid/reconnect/99999')
    assert res.status_code == 404


def test_reconnect_requires_auth(client, app):
    inst_id = _make_login_required_institution(app)
    res = client.post(f'/api/plaid/reconnect/{inst_id}')
    assert res.status_code == 302
    with app.app_context():
        # Status unchanged because the endpoint never ran.
        assert db.session.get(Institution, inst_id).status == 'login_required'


def _make_account(app, inst_id, plaid_account_id='acc-001', name='Sapphire', mask='1234',
                  current_balance=None, next_payment_due_date=None,
                  last_statement_balance=None, minimum_payment_amount=None):
    with app.app_context():
        acct = Account(
            institution_id=inst_id,
            plaid_account_id=plaid_account_id,
            name=name,
            mask=mask,
            type='credit',
            subtype='credit card',
            current_balance=Decimal(str(current_balance)) if current_balance is not None else None,
            next_payment_due_date=next_payment_due_date,
            last_statement_balance=(
                Decimal(str(last_statement_balance)) if last_statement_balance is not None else None
            ),
            minimum_payment_amount=(
                Decimal(str(minimum_payment_amount)) if minimum_payment_amount is not None else None
            ),
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


def test_index_account_card_renders_balance_and_filter_sum(auth_client, app):
    inst_id = _make_institution(app, name='Chase', slug='chase')
    _make_account(app, inst_id, plaid_account_id='acc-bal', name='Sapphire', mask='4242',
                  current_balance='1234.56')
    _make_txn_row(app, inst_id, 'acc-bal', 'b-1', '10.00', date(2026, 5, 1))
    _make_txn_row(app, inst_id, 'acc-bal', 'b-2', '5.50', date(2026, 5, 2))

    res = auth_client.get('/')
    assert res.status_code == 200
    # Headline = current_balance (no leading sign)
    assert b'$1234.56' in res.data
    # Secondary line = filtered transaction sum, labeled and signed
    assert b'This filter: -$15.50' in res.data
    assert b'2 txns' in res.data


def test_index_account_card_renders_dash_when_balance_missing(auth_client, app):
    inst_id = _make_institution(app, name='Truist', slug='truist')
    _make_account(app, inst_id, plaid_account_id='acc-no-bal', name='Fresh Checking')

    res = auth_client.get('/')
    assert res.status_code == 200
    assert b'Fresh Checking' in res.data
    # No balance → em dash placeholder, NOT $0.00 as the headline
    assert '—'.encode('utf-8') in res.data


def test_index_account_totals_include_current_balance(auth_client, app):
    inst_id = _make_institution(app, name='Citi', slug='citi')
    _make_account(app, inst_id, plaid_account_id='acc-cb', name='Double Cash',
                  current_balance='42.00')

    with auth_client.application.test_request_context('/'):
        from app.routes import _account_totals
        rows = _account_totals(None, None, None)

    matching = [r for r in rows if r.account_name == 'Double Cash']
    assert len(matching) == 1
    assert matching[0].current_balance == Decimal('42.00')


def test_index_account_totals_include_liability_fields(auth_client, app):
    inst_id = _make_institution(app, name='Citi', slug='citi')
    _make_account(app, inst_id, plaid_account_id='acc-l', name='Double Cash',
                  next_payment_due_date=date(2026, 8, 1),
                  last_statement_balance='250.00', minimum_payment_amount='25.00')

    with auth_client.application.test_request_context('/'):
        from app.routes import _account_totals
        rows = _account_totals(None, None, None)

    match = [r for r in rows if r.account_name == 'Double Cash'][0]
    assert match.next_payment_due_date == date(2026, 8, 1)
    assert match.last_statement_balance == Decimal('250.00')
    assert match.minimum_payment_amount == Decimal('25.00')


def test_index_account_card_renders_due_date_and_balance_due(auth_client, app):
    inst_id = _make_institution(app, name='Chase', slug='chase')
    # Far-future due date so it renders "Due" (not "Overdue") regardless of the
    # real date the test runs on.
    _make_account(app, inst_id, plaid_account_id='acc-liab', name='Sapphire', mask='4242',
                  current_balance='1000.00', next_payment_due_date=date(2099, 12, 25),
                  last_statement_balance='432.10', minimum_payment_amount='35.00')

    res = auth_client.get('/')
    assert res.status_code == 200
    assert b'Due Dec 25' in res.data
    assert b'$432.10' in res.data
    assert b'min $35.00 due' in res.data


def test_index_account_card_marks_overdue_payment(auth_client, app):
    inst_id = _make_institution(app, name='Amex', slug='amex')
    # Far-past due date so it always renders as overdue.
    _make_account(app, inst_id, plaid_account_id='acc-od', name='Platinum',
                  next_payment_due_date=date(2000, 1, 5), last_statement_balance='99.00')

    res = auth_client.get('/')
    assert res.status_code == 200
    assert b'Overdue Jan 5' in res.data


def test_index_account_card_omits_liability_line_without_data(auth_client, app):
    inst_id = _make_institution(app, name='Truist', slug='truist')
    _make_account(app, inst_id, plaid_account_id='acc-dep', name='Fresh Checking')

    res = auth_client.get('/')
    assert res.status_code == 200
    assert b'Fresh Checking' in res.data
    # No liability data → no due-date / balance-due line.
    assert b'Due ' not in res.data
    assert b'Overdue' not in res.data
    assert b'min $' not in res.data


def test_index_account_totals_include_zero_txn_accounts(auth_client, app):
    # Approach §5: a freshly-linked account renders with $0.00 even when no
    # transactions yet match the active filter.
    inst_id = _make_institution(app, name='Truist', slug='truist')
    _make_account(app, inst_id, plaid_account_id='acc-fresh', name='Fresh Checking', mask='0000')

    res = auth_client.get('/')
    assert res.status_code == 200
    assert b'Fresh Checking' in res.data
    assert b'$0.00' in res.data
    assert b'0 txns' in res.data


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


# ── Week grouping ─────────────────────────────────────────────────────────────

class _FakeTxn:
    def __init__(self, d):
        self.date = d


def test_group_by_week_sunday_boundary():
    from app.routes import _group_by_week
    # 2026-06-07 is a Sunday; 2026-06-13 is a Saturday (same week)
    # 2026-06-14 is the next Sunday (new week)
    txns = [_FakeTxn(date(2026, 6, 14)), _FakeTxn(date(2026, 6, 13)), _FakeTxn(date(2026, 6, 7))]
    groups = _group_by_week(txns)
    assert len(groups) == 2
    label0, group0 = groups[0]
    label1, group1 = groups[1]
    assert group0 == [txns[0]]
    assert group1 == [txns[1], txns[2]]
    assert 'Jun 14' in label0
    assert 'Jun 7' in label1
    assert '13' in label1


def test_group_by_week_empty():
    from app.routes import _group_by_week
    assert _group_by_week([]) == []


def test_group_by_week_cross_month():
    from app.routes import _group_by_week
    # May 31, 2026 is a Sunday; Jun 1 is in the same week
    txns = [_FakeTxn(date(2026, 6, 1)), _FakeTxn(date(2026, 5, 31))]
    groups = _group_by_week(txns)
    assert len(groups) == 1
    label, group = groups[0]
    assert len(group) == 2
    assert 'May 31' in label
    assert 'Jun 6' in label


def test_index_shows_week_headers(auth_client, app):
    inst_id = _make_institution(app)
    _make_account(app, inst_id)
    # Mon Jun 1 → preceding Sunday May 31 → week header "May 31 – Jun 6, 2026"
    # Mon Jun 8 → preceding Sunday Jun 7  → week header "Jun 7–13, 2026"
    _make_txn_row(app, inst_id, 'acc-001', 'w1', '5.00', date(2026, 6, 1))
    _make_txn_row(app, inst_id, 'acc-001', 'w2', '8.00', date(2026, 6, 8))
    res = auth_client.get('/')
    assert res.status_code == 200
    assert b'Jun 7' in res.data
    assert b'May 31' in res.data


# ── /api/transactions ──────────────────────────────────────────────────────────

def _seed_transactions(app, inst_id, count, prefix='txn', account_id='acc-001'):
    with app.app_context():
        for i in range(count):
            db.session.add(Transaction(
                plaid_transaction_id=f'{prefix}-{i:03d}',
                institution_id=inst_id,
                account_id=account_id,
                date=date(2026, 5, 1),
                description=f'Merchant {i}',
                amount=Decimal('10.00'),
            ))
        db.session.commit()


def test_transactions_json_page1(auth_client, app):
    inst_id = _make_institution(app)
    _seed_transactions(app, inst_id, count=60)

    res = auth_client.get('/api/transactions?page=1')
    assert res.status_code == 200
    data = res.json
    assert len(data['items']) == 50
    assert data['has_next'] is True
    assert data['next_page'] == 2


def test_transactions_json_page2(auth_client, app):
    inst_id = _make_institution(app)
    _seed_transactions(app, inst_id, count=60)

    res = auth_client.get('/api/transactions?page=2')
    assert res.status_code == 200
    data = res.json
    assert len(data['items']) == 10
    assert data['has_next'] is False


def test_transactions_json_institution_filter(auth_client, app):
    inst_id = _make_institution(app, name='AmEx', slug='amex')
    inst2_id = _make_institution(app, name='Citi', slug='citi')
    _seed_transactions(app, inst_id, count=1, prefix='amex')
    _seed_transactions(app, inst2_id, count=1, prefix='citi')

    res = auth_client.get(f'/api/transactions?institution={inst_id}')
    assert res.status_code == 200
    data = res.json
    assert len(data['items']) == 1
    assert data['items'][0]['institution_name'] == 'AmEx'


def _seed_two_dated(app, inst_id):
    """One transaction on 2026-05-15, one on 2026-04-15, distinct descriptions."""
    with app.app_context():
        db.session.add(Transaction(
            plaid_transaction_id='mid-may', institution_id=inst_id,
            account_id='acc-001', date=date(2026, 5, 15),
            description='MidMayTxn', amount=Decimal('5.00'),
        ))
        db.session.add(Transaction(
            plaid_transaction_id='mid-apr', institution_id=inst_id,
            account_id='acc-001', date=date(2026, 4, 15),
            description='MidAprTxn', amount=Decimal('5.00'),
        ))
        db.session.commit()


def test_index_window_filter(auth_client, app):
    """?start/?end restricts the table to the [start, end) window."""
    inst_id = _make_institution(app)
    _seed_two_dated(app, inst_id)
    body = auth_client.get('/?start=2026-05-11&end=2026-05-18').get_data(as_text=True)
    assert 'MidMayTxn' in body
    assert 'MidAprTxn' not in body


def test_index_window_end_is_exclusive(auth_client, app):
    inst_id = _make_institution(app)
    _make_txn_row(app, inst_id, 'acc-001', 'boundary', '5.00', date(2026, 5, 18))
    # Window ends 2026-05-18 exclusive → the 18th is NOT included.
    body = auth_client.get('/?start=2026-05-11&end=2026-05-18').get_data(as_text=True)
    assert 'No transactions found' in body


def test_transactions_json_window_filter(auth_client, app):
    inst_id = _make_institution(app)
    _seed_two_dated(app, inst_id)
    res = auth_client.get('/api/transactions?start=2026-05-11&end=2026-05-18')
    assert res.status_code == 200
    descriptions = [i['description'] for i in res.json['items']]
    assert 'MidMayTxn' in descriptions
    assert 'MidAprTxn' not in descriptions


def test_window_takes_precedence_over_month(auth_client, app):
    """A start/end window overrides ?month= for the table."""
    inst_id = _make_institution(app)
    _seed_two_dated(app, inst_id)
    # Month says April, window says mid-May → window wins.
    body = auth_client.get('/?month=2026-04&start=2026-05-11&end=2026-05-18').get_data(as_text=True)
    assert 'MidMayTxn' in body
    assert 'MidAprTxn' not in body


def test_malformed_window_falls_back_to_month(auth_client, app):
    """Garbage/partial start/end is ignored (no 500); month filter still applies."""
    inst_id = _make_institution(app)
    _seed_two_dated(app, inst_id)
    # start present but unparseable, no end → falls back to ?month=2026-05.
    body = auth_client.get('/?month=2026-05&start=not-a-date').get_data(as_text=True)
    assert 'MidMayTxn' in body
    assert 'MidAprTxn' not in body


def test_window_indicator_renders(auth_client, app):
    inst_id = _make_institution(app)
    _seed_two_dated(app, inst_id)
    body = auth_client.get('/?start=2026-05-11&end=2026-05-18').get_data(as_text=True)
    assert 'Showing' in body
    assert 'Clear window' in body
    assert 'May 11' in body  # window_label start


def test_transactions_json_month_filter(auth_client, app):
    inst_id = _make_institution(app)
    with app.app_context():
        db.session.add(Transaction(
            plaid_transaction_id='may-txn',
            institution_id=inst_id,
            account_id='acc-001',
            date=date(2026, 5, 15),
            description='In May',
            amount=Decimal('5.00'),
        ))
        db.session.add(Transaction(
            plaid_transaction_id='apr-txn',
            institution_id=inst_id,
            account_id='acc-001',
            date=date(2026, 4, 15),
            description='In April',
            amount=Decimal('5.00'),
        ))
        db.session.commit()

    res = auth_client.get('/api/transactions?month=2026-05')
    assert res.status_code == 200
    data = res.json
    descriptions = [item['description'] for item in data['items']]
    assert 'In May' in descriptions
    assert 'In April' not in descriptions


def test_transactions_json_item_shape(auth_client, app):
    inst_id = _make_institution(app)
    _make_transaction(app, inst_id, description='Coffee')

    res = auth_client.get('/api/transactions')
    assert res.status_code == 200
    item = res.json['items'][0]
    assert 'date' in item
    assert 'description' in item
    assert 'merchant_name' in item
    assert 'institution_name' in item
    assert 'amount' in item
    assert 'amount_sign' in item
    assert 'amount_class' in item
