import re
from datetime import date, timedelta
from decimal import Decimal

import pytest

from app.bills import (
    INCOME_PERCENTILE, detect_bills, detect_recurring_from_groups,
    fixed_monthly_total, monthly_income_total, _expected_day_of_month,
    _monthly_estimate, _payment_status, _safe_date,
)
from app.subscriptions import _group_transactions
from app.models import db, Institution, Transaction, Account

TODAY = date(2026, 6, 13)


class FakeTxn:
    def __init__(self, txn_date, amount='120.00', merchant_name=None,
                 description=None, merchant_entity_id=None,
                 institution_id=1, account_id='acc-1', removed=False,
                 category=None, category_detailed=None):
        self.date = txn_date
        self.amount = Decimal(amount)
        self.merchant_name = merchant_name
        # Real rows always carry the card descriptor, and it usually reads like
        # the merchant; a shared placeholder would make every fixture one
        # descriptor and merge unrelated merchants (merge_by_descriptor).
        self.description = description or merchant_name or 'CHARGE'
        self.merchant_entity_id = merchant_entity_id
        self.institution_id = institution_id
        self.account_id = account_id
        self.removed = removed
        self.category = category
        self.category_detailed = category_detailed


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


@pytest.mark.parametrize('path', ['/recurring', '/bills', '/subscriptions'])
def test_recurring_pages_require_login(client, path):
    res = client.get(path)
    assert res.status_code == 302
    assert '/login' in res.headers['Location']


@pytest.mark.parametrize('path', ['/bills', '/subscriptions'])
def test_old_pages_redirect_to_recurring(auth_client, path):
    """Temporary redirects: a cached 301 would outlive a rollback."""
    res = auth_client.get(path)
    assert res.status_code == 302
    assert res.headers['Location'].endswith('/recurring')


def test_nav_has_one_recurring_link(auth_client):
    res = auth_client.get('/recurring')
    assert res.data.count(b'href="/recurring"') == 1
    assert b'href="/bills"' not in res.data
    assert b'href="/subscriptions"' not in res.data


def test_recurring_page_renders_stream(auth_client, app):
    _seed_recurring_outflow(app)
    res = auth_client.get('/recurring')
    assert res.status_code == 200
    assert b'Electric Co' in res.data
    assert b'95.00' in res.data
    assert b'Test Bank' in res.data


def test_recurring_page_empty_state(auth_client):
    res = auth_client.get('/recurring')
    assert res.status_code == 200
    assert b'No recurring expenses detected yet' in res.data
    assert b'No recurring income detected yet' in res.data
    assert b'Left after recurring' not in res.data


# ── Fixed monthly total ───────────────────────────────────────────────────────

def _only_bill(txns):
    bills = detect_bills(txns, TODAY)
    assert len(bills) == 1, bills
    return bills[0]


def test_fixed_price_bill_counts_at_its_price():
    bill = _only_bill(monthly_bill(6, day=10, amount='15.00', description='STREAMING'))
    assert bill['monthly_amount'] == Decimal('15.00')
    assert bill['excluded_reason'] is None


def test_variable_bill_leans_high():
    """P75 by linear interpolation: position 0.75 * 11 = 8.25 of the sorted
    year, so 150 + (200 - 150) * 0.25 = 162.50 — above the 105 median."""
    amounts = ['100', '100', '100', '100', '100', '100',
               '110', '120', '150', '200', '250', '300']
    txns = [FakeTxn(d.date, amount=a, description='POWER CO')
            for d, a in zip(monthly_bill(12, day=10, start_month=6, start_year=2025),
                            amounts)]
    bill = _only_bill(txns)
    assert bill['monthly_amount'] == Decimal('162.50')
    assert bill['monthly_amount'] > bill['amount']


def test_charges_older_than_a_year_are_ignored():
    old = monthly_bill(4, day=10, start_month=1, start_year=2025,
                       amount='999.00', description='INTERNET')
    recent = monthly_bill(12, day=10, start_month=6, start_year=2025,
                          amount='50.00', description='INTERNET')
    assert _only_bill(old + recent)['monthly_amount'] == Decimal('50.00')


def test_same_day_charges_are_one_occurrence():
    txns = (monthly_bill(6, day=10, amount='10.00', description='APPLE')
            + monthly_bill(6, day=10, amount='5.00', description='APPLE'))
    assert _only_bill(txns)['monthly_amount'] == Decimal('15.00')


def test_refund_does_not_lower_the_estimate():
    """Without the positive-amount filter the refund is its own occurrence and
    P75 of [-50, 100] is 62.50; with it, only the charge counts."""
    txns = [FakeTxn(date(2026, 5, 10), amount='100.00'),
            FakeTxn(date(2026, 5, 20), amount='-50.00')]
    assert _monthly_estimate(txns, 'monthly') == Decimal('100.00')


def test_window_holds_twelve_monthly_occurrences():
    """The charge exactly a year before the latest falls outside the window, or
    the latest month would effectively be counted twice."""
    txns = [FakeTxn(d.date, amount='100.00') for d in
            monthly_bill(12, day=10, start_month=6, start_year=2025)]
    txns.append(FakeTxn(date(2025, 5, 10), amount='900.00'))  # 365 days before
    assert _monthly_estimate(txns, 'monthly') == Decimal('100.00')


def test_uncategorized_history_does_not_outvote_card_payments():
    old = monthly_bill(8, day=10, start_month=1, start_year=2025,
                       amount='2000.00', description='CARD AUTOPAY')
    new = monthly_bill(5, day=10, start_month=2, amount='2000.00',
                       description='CARD AUTOPAY', category='LOAN_PAYMENTS',
                       category_detailed='LOAN_PAYMENTS_CREDIT_CARD_PAYMENT')
    # Fill the gap so the stream stays regular month to month.
    gap = monthly_bill(4, day=10, start_month=9, start_year=2025,
                       amount='2000.00', description='CARD AUTOPAY')
    assert _only_bill(old + gap + new)['excluded_reason'] == 'transfer'


@pytest.mark.parametrize('cadence, amount, expected', [
    ('weekly', '100.00', '433.33'),
    ('biweekly', '100.00', '216.67'),
    ('monthly', '100.00', '100.00'),
    ('quarterly', '90.00', '30.00'),
    ('annual', '120.00', '10.00'),
])
def test_single_occurrence_scaled_by_cadence(cadence, amount, expected):
    txns = [FakeTxn(date(2026, 6, 1), amount=amount)]
    assert _monthly_estimate(txns, cadence) == Decimal(expected)


def test_inactive_bill_is_not_counted():
    bill = _only_bill(monthly_bill(3, day=10, description='OLD GYM'))  # last Mar 10
    assert bill['excluded_reason'] == 'inactive'


def test_inactive_annual_bill_reports_inactive():
    txns = [FakeTxn(date(2023, 6, 1), description='DOMAIN'),
            FakeTxn(date(2024, 6, 1), description='DOMAIN')]
    assert _only_bill(txns)['excluded_reason'] == 'inactive'


def test_active_annual_bill_is_not_counted():
    txns = [FakeTxn(date(2024, 6, 1), amount='120.00', description='DOMAIN'),
            FakeTxn(date(2025, 6, 1), amount='120.00', description='DOMAIN')]
    bill = _only_bill(txns)
    assert bill['excluded_reason'] == 'annual'
    assert bill['monthly_amount'] == Decimal('10.00')


@pytest.mark.parametrize('category, detailed, expected', [
    ('TRANSFER_OUT', 'TRANSFER_OUT_SAVINGS', 'transfer'),
    ('LOAN_PAYMENTS', 'LOAN_PAYMENTS_CREDIT_CARD_PAYMENT', 'transfer'),
    ('LOAN_PAYMENTS', 'LOAN_PAYMENTS_MORTGAGE_PAYMENT', None),
    (None, None, None),
])
def test_card_payments_and_transfers_are_not_counted(category, detailed, expected):
    txns = monthly_bill(6, day=10, description='PAYMENT',
                        category=category, category_detailed=detailed)
    assert _only_bill(txns)['excluded_reason'] == expected


def test_fixed_monthly_total_sums_counted_bills():
    bills = [
        {'monthly_amount': Decimal('15.00'), 'excluded_reason': None},
        {'monthly_amount': Decimal('240.25'), 'excluded_reason': None},
        {'monthly_amount': Decimal('900.00'), 'excluded_reason': 'annual'},
        {'monthly_amount': Decimal('20.00'), 'excluded_reason': 'inactive'},
    ]
    assert fixed_monthly_total(bills) == (Decimal('255.25'), 2)
    assert fixed_monthly_total([]) == (Decimal('0.00'), 0)


def test_recurring_page_renders_expense_total(auth_client, app):
    _seed_recurring_outflow(app)
    with app.app_context():
        inst = Institution.query.first()
        today = date.today()
        for i, days in enumerate((60, 30, 0)):
            db.session.add(Transaction(
                plaid_transaction_id=f'xfer-{i}', institution_id=inst.id,
                account_id='acc-1', date=today - timedelta(days=days),
                description='Savings Transfer', merchant_name='Savings Transfer',
                amount=Decimal('500.00'), category='TRANSFER_OUT',
            ))
        db.session.commit()
    res = auth_client.get('/recurring')
    assert res.status_code == 200
    assert b'Recurring expenses' in res.data
    assert b'$95.00 / month' in res.data
    assert re.search(rb'\b1 expense\s', res.data)  # the transfer is not counted
    assert b'Per month' in res.data
    assert b'Transfers (1)' in res.data
    assert b'not counted: transfer' in res.data


# ── Recurring income ──────────────────────────────────────────────────────────

def biweekly_deposits(n, last=TODAY, amount='-2000.00', description='ACME PAYROLL',
                      category='INCOME', category_detailed='INCOME_WAGES', **kwargs):
    """n deposits 14 days apart, the latest on `last` (amounts are negative:
    money in)."""
    return [FakeTxn(last - timedelta(days=14 * i), amount=amount,
                    description=description, category=category,
                    category_detailed=category_detailed, **kwargs)
            for i in range(n)]


def _only_income(txns):
    bills, income = detect_recurring_from_groups(_group_transactions(txns), TODAY)
    assert bills == [] and len(income) == 1, (bills, income)
    return income[0]


def test_paycheck_counts_at_biweekly_factor():
    """26 paychecks a year, so 2000 × 26 / 12."""
    stream = _only_income(biweekly_deposits(10))
    assert stream['cadence'] == 'biweekly'
    assert stream['monthly_amount'] == Decimal('4333.33')
    assert stream['excluded_reason'] is None


def test_variable_income_leans_low():
    """P25 by linear interpolation: position 0.25 * 7 = 1.75 of the sorted
    deposits, so 1000 + (2000 - 1000) * 0.75 = 1750 per paycheck."""
    amounts = ['-900', '-1000', '-2000', '-2000', '-2000', '-2000', '-2500', '-3000']
    txns = [FakeTxn(t.date, amount=a, description='ACME PAYROLL', category='INCOME')
            for t, a in zip(biweekly_deposits(8), amounts)]
    assert _monthly_estimate(txns, 'monthly', inflow=True,
                             percentile=INCOME_PERCENTILE) == Decimal('1750.00')


def test_income_ignores_positive_rows_and_sums_same_day_deposits():
    txns = [FakeTxn(date(2026, 6, 1), amount='-1500.00'),
            FakeTxn(date(2026, 6, 1), amount='-500.00'),   # same day: one occurrence
            FakeTxn(date(2026, 6, 5), amount='300.00')]    # a clawback, ignored
    assert _monthly_estimate(txns, 'monthly', inflow=True,
                             percentile=INCOME_PERCENTILE) == Decimal('2000.00')


def test_income_older_than_a_year_is_ignored():
    """Old deposits drop out of the window, so a raise shows up in the figure."""
    recent = biweekly_deposits(27)                       # 0..364 days back
    old = biweekly_deposits(10, last=TODAY - timedelta(days=378), amount='-100.00')
    assert _monthly_estimate(recent + old, 'biweekly', inflow=True,
                             percentile=INCOME_PERCENTILE) == Decimal('4333.33')


def test_income_window_excludes_its_far_end():
    """A deposit exactly 365 days before the latest is outside the window —
    the same exclusive far end as expenses. With it, P25 of [100, 2000, 2000]
    would be 1050; without it, both remaining deposits are 2000."""
    txns = [FakeTxn(TODAY, amount='-2000.00'),
            FakeTxn(TODAY - timedelta(days=30), amount='-2000.00'),
            FakeTxn(TODAY - timedelta(days=365), amount='-100.00')]
    assert _monthly_estimate(txns, 'monthly', inflow=True,
                             percentile=INCOME_PERCENTILE) == Decimal('2000.00')


def test_income_estimate_with_no_deposits_is_zero():
    txns = [FakeTxn(date(2026, 6, 1), amount='50.00')]
    assert _monthly_estimate(txns, 'monthly', inflow=True,
                             percentile=INCOME_PERCENTILE) == Decimal('0.00')


@pytest.mark.parametrize('category, detailed, expected', [
    ('INCOME', 'INCOME_WAGES', None),
    ('INCOME', 'INCOME_INTEREST_EARNED', None),
    ('TRANSFER_IN', 'TRANSFER_IN_ACCOUNT_TRANSFER', 'not income'),
    ('LOAN_PAYMENTS', 'LOAN_PAYMENTS_CREDIT_CARD_PAYMENT', 'not income'),
    (None, None, 'not income'),  # no category evidence: never counted as income
])
def test_only_income_categorized_inflows_count(category, detailed, expected):
    txns = biweekly_deposits(8, category=category, category_detailed=detailed)
    assert _only_income(txns)['excluded_reason'] == expected


def test_uncategorized_history_does_not_outvote_income_rows():
    old = biweekly_deposits(6, last=TODAY - timedelta(days=84),
                            category=None, category_detailed=None)
    new = biweekly_deposits(6)
    assert _only_income(old + new)['excluded_reason'] is None


def test_lapsed_income_is_not_counted():
    stream = _only_income(biweekly_deposits(8, last=TODAY - timedelta(days=60)))
    assert stream['excluded_reason'] == 'inactive'


def test_annual_income_is_not_counted():
    txns = [FakeTxn(date(2025, 6, 1), amount='-1200.00', description='BONUS',
                    category='INCOME'),
            FakeTxn(date(2026, 6, 1), amount='-1200.00', description='BONUS',
                    category='INCOME')]
    stream = _only_income(txns)
    assert stream['excluded_reason'] == 'annual'
    assert stream['monthly_amount'] == Decimal('100.00')


def test_monthly_income_total_sums_counted_streams():
    income = [
        {'monthly_amount': Decimal('4333.33'), 'excluded_reason': None},
        {'monthly_amount': Decimal('12.50'), 'excluded_reason': None},
        {'monthly_amount': Decimal('433.33'), 'excluded_reason': 'not income'},
    ]
    assert monthly_income_total(income) == (Decimal('4345.83'), 2)
    assert monthly_income_total([]) == (Decimal('0.00'), 0)


def test_recurring_detection_splits_bills_from_income_in_one_pass():
    txns = monthly_bill(6, day=10, amount='15.00', description='STREAMING') \
        + biweekly_deposits(8)
    bills, income = detect_recurring_from_groups(_group_transactions(txns), TODAY)
    assert [b['name'] for b in bills] == ['STREAMING']
    assert [s['name'] for s in income] == ['ACME PAYROLL']
    # The bills half is exactly what detect_bills returns on its own.
    assert bills == detect_bills(txns, TODAY)


# ── /recurring with income ────────────────────────────────────────────────────

def _seed_income(app, description='Acme Payroll', category='INCOME',
                 category_detailed='INCOME_WAGES', prefix='pay'):
    """Eight biweekly deposits of 2000.00 ending today."""
    with app.app_context():
        inst = Institution.query.first()
        today = date.today()
        for i in range(8):
            db.session.add(Transaction(
                plaid_transaction_id=f'{prefix}-{i}', institution_id=inst.id,
                account_id='acc-1', date=today - timedelta(days=14 * i),
                description=description, merchant_name=description,
                amount=Decimal('-2000.00'), category=category,
                category_detailed=category_detailed,
            ))
        db.session.commit()


def _section(html, start, end=None):
    """The slice of the page between two headings."""
    html = html.decode()
    tail = html[html.index(start):]
    return tail[:tail.index(end)] if end else tail


def _per_month_cells(section):
    """Per-month figures of the counted rows (rendered `medium`) in a section."""
    return [Decimal(v.replace(',', '')) for v in re.findall(
        r'class="right nowrap amount medium">\s*\$([\d,]+\.\d\d)', section)]


def test_recurring_page_shows_income_and_left_over(auth_client, app):
    _seed_recurring_outflow(app)
    _seed_income(app)
    _seed_income(app, description='Savings Sweep', category='TRANSFER_IN',
                 category_detailed='TRANSFER_IN_ACCOUNT_TRANSFER', prefix='sweep')
    res = auth_client.get('/recurring')
    assert res.status_code == 200
    assert b'Acme Payroll' in res.data
    assert b'$4,333.33 / month' in res.data      # 2000 × 26 / 12
    assert re.search(rb'\b1 source\s', res.data)  # the sweep is not income
    assert b'not counted: not income' in res.data
    assert b'Left after recurring' in res.data
    assert b'$4,238.33 / month' in res.data      # 4333.33 − 95.00


def test_recurring_headlines_match_their_rows(auth_client, app):
    _seed_recurring_outflow(app)
    _seed_income(app)
    with app.app_context():
        inst = Institution.query.first()
        today = date.today()
        for i, days in enumerate((60, 30, 0)):
            db.session.add(Transaction(
                plaid_transaction_id=f'net-{i}', institution_id=inst.id,
                account_id='acc-1', date=today - timedelta(days=days),
                description='Streamflix', merchant_name='Streamflix',
                amount=Decimal('15.49'),
            ))
        db.session.commit()
        rows = Transaction.query.all()
        expected_total, _ = fixed_monthly_total(detect_bills(rows, today))
    res = auth_client.get('/recurring')

    expenses = _section(res.data, 'Counted expenses', 'Recurring income</div>')
    assert sum(_per_month_cells(expenses)) == expected_total == Decimal('110.49')
    assert f'${expected_total:,.2f} / month'.encode() in res.data

    income = _section(res.data, 'Recurring income</div>')
    assert sum(_per_month_cells(income)) == Decimal('4333.33')


def test_not_counted_rows_carry_no_payment_badge(auth_client, app):
    """An annual stream whose day this month has passed would read "Unpaid" if
    it carried a status; uncounted rows carry none (knowledge 005)."""
    with app.app_context():
        inst = Institution(name='Test Bank', slug='test_bank',
                           access_token='tok', item_id='item-1')
        db.session.add(inst)
        db.session.flush()
        today = date.today()
        for i, days in enumerate((370, 5)):
            db.session.add(Transaction(
                plaid_transaction_id=f'annual-{i}', institution_id=inst.id,
                account_id='acc-1', date=today - timedelta(days=days),
                description='Domain Renewal', merchant_name='Domain Renewal',
                amount=Decimal('120.00'),
            ))
        db.session.commit()
    res = auth_client.get('/recurring')
    not_counted = _section(res.data, 'Not counted', 'Recurring income</div>')
    assert 'Domain Renewal' in not_counted
    assert 'Annual (1)' in not_counted
    assert 'badge-danger' not in not_counted
    assert 'badge-success' not in not_counted


def test_every_bill_exclusion_reason_has_a_group(auth_client, app, monkeypatch):
    """A reason the page has no heading for still renders, under its own name,
    so no uncounted bill silently drops off the page."""
    import app.bills as bills_module
    _seed_recurring_outflow(app)
    monkeypatch.setattr(bills_module, '_excluded_reason', lambda stream, txns: 'paused')
    res = auth_client.get('/recurring')
    not_counted = _section(res.data, 'Not counted', 'Recurring income</div>')
    assert 'Paused (1)' in not_counted
    assert 'Electric Co' in not_counted


def test_counted_expenses_are_largest_first(auth_client, app):
    _seed_recurring_outflow(app)                                    # 95.00
    with app.app_context():
        inst = Institution.query.first()
        today = date.today()
        for i, days in enumerate((60, 30, 0)):
            db.session.add(Transaction(
                plaid_transaction_id=f'rent-{i}', institution_id=inst.id,
                account_id='acc-1', date=today - timedelta(days=days),
                description='Maple Apartments', merchant_name='Maple Apartments',
                amount=Decimal('1800.00'),
            ))
        db.session.commit()
    res = auth_client.get('/recurring')
    expenses = _section(res.data, 'Counted expenses', 'Recurring income</div>')
    assert expenses.index('Maple Apartments') < expenses.index('Electric Co')


def test_left_over_renders_negative_when_expenses_exceed_income(auth_client, app):
    _seed_recurring_outflow(app)
    with app.app_context():
        inst = Institution.query.first()
        today = date.today()
        for i, days in enumerate((60, 30, 0)):
            db.session.add(Transaction(
                plaid_transaction_id=f'int-{i}', institution_id=inst.id,
                account_id='acc-1', date=today - timedelta(days=days),
                description='Interest Paid', merchant_name='Interest Paid',
                amount=Decimal('-40.00'), category='INCOME',
                category_detailed='INCOME_INTEREST_EARNED',
            ))
        db.session.commit()
    res = auth_client.get('/recurring')
    left = _section(res.data, 'Left after recurring', 'Counted expenses')
    assert 'text-danger' in left
    assert '-$55.00 / month' in left  # 40.00 income − 95.00 expenses


def test_recurring_counts_a_renamed_merchant_once(auth_client, app):
    """Plaid renamed the merchant; the card descriptor stayed. One bill, counted."""
    with app.app_context():
        inst = Institution(name='Test Bank', slug='test_bank',
                           access_token='tok', item_id='item-1')
        db.session.add(inst)
        db.session.flush()
        today = date.today()
        for i in range(12):
            renamed = i < 2
            db.session.add(Transaction(
                plaid_transaction_id=f'renamed-{i}', institution_id=inst.id,
                account_id='acc-1', date=today - timedelta(days=30 * i),
                description='PAYCO* CONTOSO SERVICES',
                merchant_name='Fabrikam Inc' if renamed else 'Contoso Ltd',
                merchant_entity_id='ent-fabrikam' if renamed else None,
                amount=Decimal('250.00'),
            ))
        db.session.commit()
    res = auth_client.get('/recurring')
    expenses = _section(res.data, 'Counted expenses', 'Recurring income</div>')
    assert expenses.count('Contoso Ltd') == 1
    assert 'Fabrikam Inc' not in res.data.decode()
    assert _per_month_cells(expenses) == [Decimal('250.00')]
    assert b'$250.00 / month' in res.data
    assert re.search(rb'\b1 expense\s', res.data)
