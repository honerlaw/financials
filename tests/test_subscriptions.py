from datetime import date, timedelta
from decimal import Decimal

from app.models import db, Institution, Transaction, Account
from app.subscriptions import detect_subscriptions, normalize_merchant

TODAY = date(2026, 6, 1)


class FakeTxn:
    """Minimal stand-in for a Transaction row — detection is a pure function."""

    def __init__(self, txn_date, amount='15.49', merchant_name=None,
                 description='CHARGE', merchant_entity_id=None,
                 institution_id=1, account_id='acc-1', removed=False):
        self.date = txn_date
        self.amount = Decimal(amount)
        self.merchant_name = merchant_name
        self.description = description
        self.merchant_entity_id = merchant_entity_id
        self.institution_id = institution_id
        self.account_id = account_id
        self.removed = removed


def monthly_txns(n, start=date(2026, 1, 5), **kwargs):
    """n charges on the 5th of consecutive months."""
    txns = []
    for i in range(n):
        month = start.month + i
        year = start.year + (month - 1) // 12
        month = (month - 1) % 12 + 1
        txns.append(FakeTxn(date(year, month, start.day), **kwargs))
    return txns


# ── Normalization & grouping ─────────────────────────────────────────────────

def test_normalize_strips_digits_punctuation_and_noise():
    assert normalize_merchant('NETFLIX.COM 866-579-7172') == 'netflix'
    assert normalize_merchant('Netflix') == 'netflix'


def test_merchant_name_variants_do_not_split_a_stream():
    txns = [
        FakeTxn(date(2026, 1, 5), merchant_name='Netflix', description='Netflix'),
        FakeTxn(date(2026, 2, 5), merchant_name=None,
                description='NETFLIX.COM 866-579-7172'),
        FakeTxn(date(2026, 3, 5), merchant_name=None,
                description='NETFLIX.COM 866-579-7172'),
        FakeTxn(date(2026, 4, 5), merchant_name='Netflix', description='Netflix'),
        FakeTxn(date(2026, 5, 5), merchant_name='Netflix', description='Netflix'),
    ]
    streams = detect_subscriptions(txns, TODAY)
    assert len(streams) == 1
    assert streams[0]['count'] == 5


def test_prefix_variants_merge():
    txns = (
        monthly_txns(3, merchant_name='Spotify')
        + monthly_txns(2, start=date(2026, 4, 5), merchant_name=None,
                       description='SPOTIFY USA 12345')
    )
    streams = detect_subscriptions(txns, TODAY)
    assert len(streams) == 1


def test_entity_id_groups_across_name_changes():
    txns = [
        FakeTxn(date(2026, 1, 5), merchant_name='Hulu', merchant_entity_id='ent-1'),
        FakeTxn(date(2026, 2, 5), merchant_name='Hulu LLC', merchant_entity_id='ent-1'),
        FakeTxn(date(2026, 3, 5), merchant_name='Hulu', merchant_entity_id='ent-1'),
        FakeTxn(date(2026, 4, 5), merchant_name='Hulu', merchant_entity_id='ent-1'),
    ]
    streams = detect_subscriptions(txns, TODAY)
    assert len(streams) == 1
    assert streams[0]['name'] == 'Hulu'


def test_card_switch_does_not_split_stream():
    txns = (
        monthly_txns(3, merchant_name='Netflix', institution_id=1, account_id='amex')
        + monthly_txns(2, start=date(2026, 4, 5), merchant_name='Netflix',
                       institution_id=2, account_id='citi')
    )
    streams = detect_subscriptions(txns, TODAY)
    assert len(streams) == 1
    assert streams[0]['active'] is True
    assert set(streams[0]['account_keys']) == {(1, 'amex'), (2, 'citi')}


# ── Cadence buckets ──────────────────────────────────────────────────────────

def test_weekly_cadence():
    start = date(2026, 4, 6)
    txns = [FakeTxn(start + timedelta(weeks=i), merchant_name='Gym') for i in range(8)]
    streams = detect_subscriptions(txns, TODAY)
    assert len(streams) == 1
    assert streams[0]['cadence'] == 'weekly'


def test_biweekly_cadence():
    start = date(2026, 3, 6)
    txns = [FakeTxn(start + timedelta(days=14 * i), amount='-2500.00',
                    merchant_name='Employer Payroll') for i in range(6)]
    streams = detect_subscriptions(txns, TODAY)
    assert streams[0]['cadence'] == 'biweekly'
    assert streams[0]['is_inflow'] is True


def test_monthly_cadence_with_day_jitter():
    # 5th, then 8th, then 3rd — day-of-month wobble stays monthly
    txns = [
        FakeTxn(date(2026, 1, 5), merchant_name='Netflix'),
        FakeTxn(date(2026, 2, 8), merchant_name='Netflix'),
        FakeTxn(date(2026, 3, 3), merchant_name='Netflix'),
        FakeTxn(date(2026, 4, 6), merchant_name='Netflix'),
        FakeTxn(date(2026, 5, 5), merchant_name='Netflix'),
    ]
    streams = detect_subscriptions(txns, TODAY)
    assert len(streams) == 1
    assert streams[0]['cadence'] == 'monthly'
    assert streams[0]['next_date'] == date(2026, 5, 5) + timedelta(days=30)


def test_quarterly_cadence():
    txns = [
        FakeTxn(date(2025, 6, 1), merchant_name='Water Utility'),
        FakeTxn(date(2025, 9, 1), merchant_name='Water Utility'),
        FakeTxn(date(2025, 12, 1), merchant_name='Water Utility'),
        FakeTxn(date(2026, 3, 1), merchant_name='Water Utility'),
    ]
    streams = detect_subscriptions(txns, TODAY)
    assert streams[0]['cadence'] == 'quarterly'
    assert streams[0]['active'] is True


def test_annual_needs_only_two_occurrences():
    txns = [
        FakeTxn(date(2025, 5, 20), amount='12.00', merchant_name='Domain Registrar'),
        FakeTxn(date(2026, 5, 20), amount='12.00', merchant_name='Domain Registrar'),
    ]
    streams = detect_subscriptions(txns, TODAY)
    assert len(streams) == 1
    assert streams[0]['cadence'] == 'annual'


def test_two_occurrences_not_enough_for_monthly():
    txns = monthly_txns(2, start=date(2026, 4, 5), merchant_name='Netflix')
    assert detect_subscriptions(txns, TODAY) == []


def test_irregular_gaps_rejected():
    # Frequent grocery runs: median gap may fall in a bucket, but the gaps
    # are irregular, so no stream is detected.
    days = [0, 3, 8, 10, 17, 19, 26]
    txns = [FakeTxn(date(2026, 4, 1) + timedelta(days=d), merchant_name='Kroger')
            for d in days]
    assert detect_subscriptions(txns, TODAY) == []


# ── Amounts ──────────────────────────────────────────────────────────────────

def test_amount_jitter_never_gates_detection():
    # Card-payment-style stream: wildly varying amounts still detected.
    amounts = ['500.00', '3000.00', '1200.00', '750.00', '2100.00']
    txns = [t for i, t in enumerate(
        monthly_txns(5, merchant_name='AmEx ePayment'))]
    for txn, amt in zip(txns, amounts):
        txn.amount = Decimal(amt)
    streams = detect_subscriptions(txns, TODAY)
    assert len(streams) == 1
    assert streams[0]['varies'] is True
    assert streams[0]['amount'] == Decimal('1200.00')  # median


def test_fixed_price_stream_has_no_varies_badge():
    streams = detect_subscriptions(
        monthly_txns(5, merchant_name='Netflix', amount='15.49'), TODAY)
    assert streams[0]['varies'] is False


def test_price_hike_does_not_set_varies():
    txns = monthly_txns(5, merchant_name='Netflix', amount='15.49')
    txns[-1].amount = Decimal('17.99')
    streams = detect_subscriptions(txns, TODAY)
    assert len(streams) == 1
    assert streams[0]['varies'] is False


# ── Active / inactive ────────────────────────────────────────────────────────

def test_active_within_inactive_boundary():
    # Monthly cadence: inactive only when overdue by > 1.5 x 30 = 45 days.
    txns = monthly_txns(4, merchant_name='Netflix')  # last charge Apr 5
    streams = detect_subscriptions(txns, date(2026, 4, 5) + timedelta(days=45))
    assert streams[0]['active'] is True


def test_inactive_past_boundary():
    txns = monthly_txns(4, merchant_name='Netflix')  # last charge Apr 5
    streams = detect_subscriptions(txns, date(2026, 4, 5) + timedelta(days=46))
    assert streams[0]['active'] is False


def test_removed_transactions_excluded():
    txns = monthly_txns(3, merchant_name='Netflix')
    for t in txns:
        t.removed = True
    assert detect_subscriptions(txns, TODAY) == []


def test_streams_sorted_active_first():
    active = monthly_txns(4, start=date(2026, 3, 5), merchant_name='Netflix',
                          amount='5.00')
    inactive = monthly_txns(4, start=date(2025, 8, 5), merchant_name='Old Gym',
                            amount='50.00')
    streams = detect_subscriptions(active + inactive, TODAY)
    assert [s['active'] for s in streams] == [True, False]


# ── Route ────────────────────────────────────────────────────────────────────

def _seed_recurring(app):
    with app.app_context():
        inst = Institution(name='Test Bank', slug='test_bank',
                           access_token='tok', item_id='item-1')
        db.session.add(inst)
        db.session.flush()
        db.session.add(Account(
            institution_id=inst.id, plaid_account_id='acc-1',
            name='Credit Card', mask='1234',
        ))
        # Relative to today: the route uses date.today(), so fixed dates
        # would eventually drift past the inactive boundary and flake.
        today = date.today()
        for i, d in enumerate([today - timedelta(days=60),
                               today - timedelta(days=30), today]):
            db.session.add(Transaction(
                plaid_transaction_id=f'txn-{i}', institution_id=inst.id,
                account_id='acc-1', date=d, description='Netflix',
                merchant_name='Netflix', amount=Decimal('15.49'),
            ))
        db.session.commit()


def test_subscriptions_requires_login(client):
    res = client.get('/subscriptions')
    assert res.status_code == 302
    assert '/login' in res.headers['Location']


def test_subscriptions_page_renders_stream(auth_client, app):
    _seed_recurring(app)
    res = auth_client.get('/subscriptions')
    assert res.status_code == 200
    assert b'Netflix' in res.data
    assert b'Monthly' in res.data or b'monthly' in res.data
    assert b'15.49' in res.data
    assert b'Test Bank' in res.data


def test_subscriptions_page_renders_multi_account_labels(auth_client, app):
    # One stream split across two institutions/cards must render both
    # "Institution · Account" badges on the single row.
    with app.app_context():
        amex = Institution(name='AmEx', slug='amex',
                           access_token='tok-a', item_id='item-a')
        citi = Institution(name='Citi', slug='citi',
                           access_token='tok-c', item_id='item-c')
        db.session.add_all([amex, citi])
        db.session.flush()
        db.session.add_all([
            Account(institution_id=amex.id, plaid_account_id='acc-amex',
                    name='Platinum'),
            Account(institution_id=citi.id, plaid_account_id='acc-citi',
                    name='Double Cash'),
        ])
        today = date.today()
        rows = [
            (amex.id, 'acc-amex', today - timedelta(days=90)),
            (amex.id, 'acc-amex', today - timedelta(days=60)),
            (citi.id, 'acc-citi', today - timedelta(days=30)),
            (citi.id, 'acc-citi', today),
        ]
        for i, (inst_id, acct_id, d) in enumerate(rows):
            db.session.add(Transaction(
                plaid_transaction_id=f'txn-ma-{i}', institution_id=inst_id,
                account_id=acct_id, date=d, description='Netflix',
                merchant_name='Netflix', amount=Decimal('15.49'),
            ))
        db.session.commit()

    res = auth_client.get('/subscriptions')
    assert res.status_code == 200
    assert 'AmEx · Platinum'.encode() in res.data
    assert 'Citi · Double Cash'.encode() in res.data


def test_subscriptions_page_empty_state(auth_client):
    res = auth_client.get('/subscriptions')
    assert res.status_code == 200
    assert b'No recurring transactions' in res.data
