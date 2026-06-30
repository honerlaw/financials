from datetime import date, timedelta
from decimal import Decimal

import pytest

from app.bills import detect_bills, _expected_day_of_month, _payment_status, _safe_date
from app.models import db, Institution, Transaction, Account

TODAY = date(2026, 6, 13)


class FakeTxn:
    def __init__(self, txn_date, amount='120.00', merchant_name=None,
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


def monthly_bill(n, day=10, start_month=1, start_year=2026, **kwargs):
    """n charges on the given day of consecutive months."""
    txns = []
    for i in range(n):
        month = start_month + i
        year = start_year + (month - 1) // 12
        month = (month - 1) % 12 + 1
        txns.append(FakeTxn(date(year, month, day), **kwargs))
    return txns


# ── Unit helpers ─────────────────────────────────────────────────────────────

def test_expected_day_odd():
    txns = [FakeTxn(date(2026, m, 15)) for m in range(1, 6)]
    assert _expected_day_of_month(txns) == 15


def test_expected_day_even():
    txns = [FakeTxn(date(2026, m, d)) for m, d in [(1, 14), (2, 15), (3, 14), (4, 15)]]
    assert _expected_day_of_month(txns) == 14


def test_safe_date_clamps_february():
    assert _safe_date(2026, 2, 31) == date(2026, 2, 28)


def test_safe_date_normal():
    assert _safe_date(2026, 6, 15) == date(2026, 6, 15)


# ── Payment status ────────────────────────────────────────────────────────────

def test_payment_status_paid():
    """Transaction lands on expected day — paid."""
    txns = monthly_bill(6, day=10)  # Jan–Jun, includes Jun 10
    status, expected = _payment_status(txns, TODAY)
    assert status == 'paid'
    assert expected == date(2026, 6, 10)


def test_payment_status_paid_within_window():
    """Transaction is 4 days after expected — still paid (within 6-day window)."""
    history = monthly_bill(4, day=10, start_month=1)
    late_pay = FakeTxn(date(2026, 6, 14))  # 4 days after Jun 10
    txns = history + [late_pay]
    status, _ = _payment_status(txns, TODAY)
    assert status == 'paid'


def test_payment_status_unpaid():
    """Expected day passed, no transaction this month — unpaid."""
    txns = monthly_bill(5, day=5)  # expected Jun 5, no Jun txn in history past May
    # history goes Jan-May only (5 months)
    status, expected = _payment_status(txns, TODAY)
    assert status == 'unpaid'
    assert expected == date(2026, 6, 5)


def test_payment_status_upcoming():
    """Expected day not yet reached — upcoming."""
    txns = monthly_bill(5, day=20)  # expected Jun 20, today = Jun 13
    status, expected = _payment_status(txns, TODAY)
    assert status == 'upcoming'
    assert expected == date(2026, 6, 20)


def test_payment_status_upcoming_just_before_window():
    """Day 14 is 1 day inside the 6-day window before Jun 20 → still upcoming."""
    txns = monthly_bill(5, day=20)
    # TODAY = Jun 13, window = 6 days, so upcoming if today < Jun 14
    # Jun 13 < Jun 14 → upcoming
    status, _ = _payment_status(txns, TODAY)
    assert status == 'upcoming'


# ── detect_bills integration ──────────────────────────────────────────────────

def test_inflows_excluded():
    """Inflows (negative amounts = money in) must not appear in bills."""
    inflow_txns = monthly_bill(4, day=1, amount='-3000.00', description='PAYCHECK')
    outflow_txns = monthly_bill(4, day=15, amount='250.00', description='ELECTRIC')
    bills = detect_bills(inflow_txns + outflow_txns, TODAY)
    assert all(b['is_inflow'] is False for b in bills)
    assert len(bills) == 1
    assert bills[0]['name'] == 'ELECTRIC'


def test_removed_excluded():
    """Removed transactions must not contribute to bill detection."""
    txns = monthly_bill(4, day=10, amount='100.00')
    removed = [FakeTxn(date(2026, m, 10), amount='100.00', removed=True) for m in range(1, 5)]
    bills = detect_bills(removed, TODAY)
    assert bills == []

    bills_with_live = detect_bills(txns + removed, TODAY)
    assert len(bills_with_live) == 1


def test_returns_only_recurring_outflows():
    """Non-recurring merchants must not appear."""
    recurring = monthly_bill(4, day=15, amount='80.00', description='INTERNET')
    one_off = [FakeTxn(date(2026, 3, 5), amount='500.00', description='DENTIST')]
    bills = detect_bills(recurring + one_off, TODAY)
    assert len(bills) == 1
    assert bills[0]['name'] == 'INTERNET'


def test_sort_unpaid_first():
    """Unpaid bills sort before upcoming, which sort before paid."""
    # unpaid: expected Jun 5, no Jun txn; last charge May 5 (39d ago — still active)
    unpaid = monthly_bill(5, day=5, description='ELECTRIC BILL')
    # upcoming: expected Jun 20; last charge May 20 (24d ago — still active)
    upcoming = monthly_bill(5, day=20, description='WATER BILL',
                            start_month=1, merchant_entity_id='ent-water')
    # paid: expected Jun 10, txn present (Jan–Jun includes Jun 10)
    paid = monthly_bill(6, day=10, description='PHONE BILL',
                        merchant_entity_id='ent-phone')
    bills = detect_bills(unpaid + upcoming + paid, TODAY)
    statuses = [b['payment_status'] for b in bills]
    # unpaid should come before upcoming, upcoming before paid
    unpaid_idx = statuses.index('unpaid')
    upcoming_idx = statuses.index('upcoming')
    paid_idx = statuses.index('paid')
    assert unpaid_idx < upcoming_idx < paid_idx


def test_bill_has_expected_date_field():
    """Each bill dict must carry expected_date_this_month and payment_status."""
    txns = monthly_bill(4, day=10, description='RENT')
    bills = detect_bills(txns, TODAY)
    assert len(bills) == 1
    assert 'payment_status' in bills[0]
    assert 'expected_date_this_month' in bills[0]
    assert bills[0]['expected_date_this_month'].month == TODAY.month


def test_inactive_stream_gets_inactive_status():
    """A stream past 1.5x its cadence shows 'inactive', not 'unpaid'."""
    # 4 monthly charges ending 50 days ago — past 1.5 * 30 = 45-day inactive boundary
    base = date.today() - timedelta(days=50)
    txns = [
        FakeTxn(base - timedelta(days=90), amount='80.00', description='OLD UTIL'),
        FakeTxn(base - timedelta(days=60), amount='80.00', description='OLD UTIL'),
        FakeTxn(base - timedelta(days=30), amount='80.00', description='OLD UTIL'),
        FakeTxn(base, amount='80.00', description='OLD UTIL'),
    ]
    bills = detect_bills(txns, date.today())
    assert len(bills) == 1
    assert bills[0]['payment_status'] == 'inactive'


def test_inactive_sorts_last():
    """Inactive bills sort after unpaid/upcoming/paid."""
    # Pure function takes `today` as an argument, so a FIXED today + fixed seeds
    # is deterministic (knowledge 004). Mixing fixed seeds with date.today()
    # was the bug: as real time drifted past mid-June 2026 the electric stream's
    # last charge aged beyond the 45-day active boundary and flipped to inactive.
    # unpaid: expected Jun 5, no Jun txn; last charge May 5 — still active (39d < 45d)
    unpaid = monthly_bill(5, day=5, description='ELECTRIC')
    # inactive: stopped 50 days before TODAY (> 1.5 * 30 = 45-day boundary)
    base = TODAY - timedelta(days=50)
    inactive = [
        FakeTxn(base - timedelta(days=90), amount='60.00', description='OLD GYM',
                merchant_entity_id='ent-gym'),
        FakeTxn(base - timedelta(days=60), amount='60.00', description='OLD GYM',
                merchant_entity_id='ent-gym'),
        FakeTxn(base - timedelta(days=30), amount='60.00', description='OLD GYM',
                merchant_entity_id='ent-gym'),
        FakeTxn(base, amount='60.00', description='OLD GYM',
                merchant_entity_id='ent-gym'),
    ]
    bills = detect_bills(unpaid + inactive, TODAY)
    statuses = [b['payment_status'] for b in bills]
    assert 'unpaid' in statuses
    assert 'inactive' in statuses
    assert statuses.index('inactive') > statuses.index('unpaid')


# ── Route integration tests ───────────────────────────────────────────────────

def _seed_recurring_outflow(app):
    """Seed 3 monthly outflow charges relative to today so stream stays active."""
    with app.app_context():
        inst = Institution(name='Test Bank', slug='test_bank',
                           access_token='tok', item_id='item-1')
        db.session.add(inst)
        db.session.flush()
        db.session.add(Account(
            institution_id=inst.id, plaid_account_id='acc-1',
            name='Checking', mask='9999',
        ))
        today = date.today()
        for i, d in enumerate([today - timedelta(days=60),
                                today - timedelta(days=30), today]):
            db.session.add(Transaction(
                plaid_transaction_id=f'bill-txn-{i}', institution_id=inst.id,
                account_id='acc-1', date=d, description='Electric Co',
                merchant_name='Electric Co', amount=Decimal('95.00'),
            ))
        db.session.commit()


def test_bills_requires_login(client):
    res = client.get('/bills')
    assert res.status_code == 302
    assert '/login' in res.headers['Location']


def test_bills_page_renders_stream(auth_client, app):
    _seed_recurring_outflow(app)
    res = auth_client.get('/bills')
    assert res.status_code == 200
    assert b'Electric Co' in res.data
    assert b'95.00' in res.data
    assert b'Test Bank' in res.data


def test_bills_page_empty_state(auth_client):
    res = auth_client.get('/bills')
    assert res.status_code == 200
    assert b'No recurring bills' in res.data
