from datetime import date, timedelta
from decimal import Decimal

from app.spending import (
    is_spend, week_start, daily_spend, weekly_budget, WEEKLY_BUDGET,
)
from app.models import db, Institution, Transaction


class FakeTxn:
    def __init__(self, txn_date, amount='50.00', category='FOOD_AND_DRINK'):
        self.date = txn_date
        self.amount = Decimal(amount)
        self.category = category


# ── is_spend ──────────────────────────────────────────────────────────────────

def test_is_spend_positive_outflow():
    assert is_spend(FakeTxn(date(2026, 7, 2), '25.00')) is True


def test_is_spend_inflow_excluded():
    assert is_spend(FakeTxn(date(2026, 7, 2), '-25.00')) is False


def test_is_spend_zero_excluded():
    assert is_spend(FakeTxn(date(2026, 7, 2), '0.00')) is False


def test_is_spend_transfer_excluded():
    assert is_spend(FakeTxn(date(2026, 7, 2), '500.00', category='TRANSFER_OUT')) is False


def test_is_spend_loan_payment_excluded():
    assert is_spend(FakeTxn(date(2026, 7, 2), '500.00', category='LOAN_PAYMENTS')) is False


def test_is_spend_null_category_counted():
    """Uncategorized outflow can't be classified, so it is counted as spend."""
    assert is_spend(FakeTxn(date(2026, 7, 2), '30.00', category=None)) is True
    assert is_spend(FakeTxn(date(2026, 7, 2), '30.00', category='')) is True


# ── week_start ────────────────────────────────────────────────────────────────

def test_week_start_is_sunday():
    ws = week_start(date(2026, 7, 1))  # a Wednesday
    assert ws == date(2026, 6, 28)
    assert ws.weekday() == 6  # Sunday


def test_week_start_on_sunday_is_identity():
    assert week_start(date(2026, 7, 5)) == date(2026, 7, 5)


# ── daily_spend ───────────────────────────────────────────────────────────────

def test_daily_spend_zero_fills_and_sums():
    txns = [
        FakeTxn(date(2026, 7, 2), '10.00'),
        FakeTxn(date(2026, 7, 2), '15.00'),      # same day → summed
        FakeTxn(date(2026, 7, 2), '-100.00'),    # inflow → excluded
        FakeTxn(date(2026, 7, 2), '500.00', category='TRANSFER_OUT'),  # excluded
    ]
    series = daily_spend(txns, date(2026, 7, 1), date(2026, 7, 4))
    assert series == [
        (date(2026, 7, 1), Decimal('0')),
        (date(2026, 7, 2), Decimal('25.00')),
        (date(2026, 7, 3), Decimal('0')),
    ]


def test_daily_spend_ignores_out_of_range():
    txns = [FakeTxn(date(2026, 6, 30), '10.00'), FakeTxn(date(2026, 7, 5), '10.00')]
    series = daily_spend(txns, date(2026, 7, 1), date(2026, 7, 4))
    assert all(total == Decimal('0') for _, total in series)


# ── weekly_budget ─────────────────────────────────────────────────────────────

MONTH_START = date(2026, 7, 1)
MONTH_END = date(2026, 8, 1)  # exclusive


def test_weekly_budget_returns_all_overlapping_weeks():
    weeks = weekly_budget([], MONTH_START, MONTH_END, date(2026, 7, 15))
    # July 2026 spans 5 Sun–Sat weeks (Jun 28 … Aug 1).
    assert [w['week_start'] for w in weeks] == [
        date(2026, 6, 28), date(2026, 7, 5), date(2026, 7, 12),
        date(2026, 7, 19), date(2026, 7, 26),
    ]


def test_weekly_budget_edge_week_sums_full_week_across_boundary():
    """A spend on Jun 29 (outside July, inside the first overlapping week) must
    count toward that week's total — not be dropped as out-of-month."""
    txns = [
        FakeTxn(date(2026, 6, 29), '300.00'),  # outside July, in week Jun28–Jul4
        FakeTxn(date(2026, 7, 2), '700.00'),   # inside July, same week
    ]
    weeks = weekly_budget(txns, MONTH_START, MONTH_END, date(2026, 7, 15))
    first = weeks[0]
    assert first['week_start'] == date(2026, 6, 28)
    assert first['spent'] == Decimal('1000.00')
    assert first['remaining'] == Decimal('0.00')
    assert first['over'] is False
    assert first['pct'] == 100


def test_weekly_budget_over_budget():
    txns = [FakeTxn(date(2026, 7, 13), '1200.00')]  # week Jul 12–18
    weeks = weekly_budget(txns, MONTH_START, MONTH_END, date(2026, 7, 15))
    wk = next(w for w in weeks if w['week_start'] == date(2026, 7, 12))
    assert wk['spent'] == Decimal('1200.00')
    assert wk['over'] is True
    assert wk['remaining'] == Decimal('-200.00')
    assert wk['pct'] == 120


def test_weekly_budget_current_week_flagged():
    weeks = weekly_budget([], MONTH_START, MONTH_END, date(2026, 7, 15))
    current = [w for w in weeks if w['is_current']]
    assert len(current) == 1
    assert current[0]['week_start'] == date(2026, 7, 12)  # week containing Jul 15


def test_weekly_budget_past_month_has_no_current_week():
    """Viewing a month that doesn't contain today → no running highlight."""
    weeks = weekly_budget(
        [], date(2026, 3, 1), date(2026, 4, 1), date(2026, 7, 15)
    )
    assert not any(w['is_current'] for w in weeks)


def test_weekly_budget_default_budget_is_1000():
    weeks = weekly_budget([], MONTH_START, MONTH_END, date(2026, 7, 15))
    assert all(w['budget'] == WEEKLY_BUDGET == Decimal('1000') for w in weeks)


# ── Route render ──────────────────────────────────────────────────────────────

def _seed_txn(app, txn_date, amount='42.00'):
    with app.app_context():
        inst = Institution(
            name='Test Bank', slug='test-bank',
            access_token='tok', item_id='item-1',
        )
        db.session.add(inst)
        db.session.flush()
        db.session.add(Transaction(
            plaid_transaction_id='txn-1', institution_id=inst.id,
            account_id='acc-1', date=txn_date, description='Coffee',
            amount=Decimal(amount), category='FOOD_AND_DRINK',
        ))
        db.session.commit()


def test_dashboard_renders_spending_section(app, auth_client):
    # Seed a spend in the current week so the section has data to show.
    _seed_txn(app, date.today(), '42.00')
    resp = auth_client.get('/')
    assert resp.status_code == 200
    body = resp.get_data(as_text=True)
    assert 'Spending' in body
    assert 'This week' in body


def test_dashboard_spending_section_renders_with_no_transactions(app, auth_client):
    resp = auth_client.get('/')
    assert resp.status_code == 200
    assert 'Spending' in resp.get_data(as_text=True)
