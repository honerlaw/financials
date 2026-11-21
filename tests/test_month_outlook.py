"""bills.month_outlook — this month's paid and still-due bills, for the digest."""
from datetime import date, timedelta
from decimal import Decimal

from app.bills import detect_recurring_with_rules, month_outlook
from app.subscriptions import _group_transactions
from tests.test_bills import FakeTxn


def _bill(rows, cadence='monthly', occurrence='100.00', excluded=None):
    days = {'weekly': 7, 'biweekly': 14, 'monthly': 30, 'quarterly': 91}
    return {
        'rows': rows, 'cadence': cadence, 'cadence_days': days[cadence],
        'occurrence_amount': Decimal(occurrence), 'excluded_reason': excluded,
    }


def _charges(*dates, amount='100.00', **kwargs):
    return [FakeTxn(d, amount=amount, **kwargs) for d in dates]


# ── monthly ──────────────────────────────────────────────────────────────────

def test_a_monthly_bill_charged_this_month_is_paid():
    rows = _charges(date(2026, 9, 3), date(2026, 10, 3), date(2026, 11, 3),
                    amount='87.40')
    out = month_outlook([_bill(rows)], date(2026, 11, 21))
    assert (out.paid_count, out.due_count) == (1, 0)
    assert out.paid_total == Decimal('87.40')
    assert out.due_total == 0


def test_an_uncharged_monthly_bill_is_due_at_its_typical_charge():
    rows = _charges(date(2026, 9, 25), date(2026, 10, 25))
    out = month_outlook([_bill(rows, occurrence='112.50')], date(2026, 11, 21))
    assert (out.paid_count, out.due_count) == (0, 1)
    assert out.paid_total == 0
    assert out.due_total == Decimal('112.50')


def test_a_monthly_bill_paid_on_a_drifting_day_is_still_paid():
    """Any charge this month pays it — not _payment_status's ±6-day window,
    which would call this one unpaid (issue #58)."""
    rows = _charges(date(2026, 9, 25), date(2026, 10, 25), date(2026, 11, 2))
    out = month_outlook([_bill(rows)], date(2026, 11, 21))
    assert (out.paid_count, out.due_count) == (1, 0)


# ── weekly / biweekly ────────────────────────────────────────────────────────

def test_a_weekly_bill_owes_each_charge_left_in_the_month():
    # Fridays; last charge Fri Nov 20, so Nov 27 is the one charge left.
    rows = _charges(date(2026, 11, 6), date(2026, 11, 13), date(2026, 11, 20),
                    amount='60.00')
    out = month_outlook([_bill(rows, 'weekly', '60.00')], date(2026, 11, 21))
    assert (out.paid_count, out.due_count) == (0, 1)
    assert out.paid_total == Decimal('180.00')
    assert out.due_total == Decimal('60.00')


def test_a_weekly_bill_early_in_the_month_owes_several_charges():
    # Last charge Fri Oct 30; Nov 6, 13, 20 and 27 are still to come.
    rows = _charges(date(2026, 10, 23), date(2026, 10, 30))
    out = month_outlook([_bill(rows, 'weekly', '60.00')], date(2026, 11, 2))
    assert out.due_total == Decimal('240.00')
    assert out.paid_total == 0


def test_a_weekly_charge_expected_today_is_still_due():
    """The digest goes out at 7am, before today's charge has posted."""
    rows = _charges(date(2026, 11, 13), date(2026, 11, 20))
    out = month_outlook([_bill(rows, 'weekly', '60.00')], date(2026, 11, 27))
    assert out.due_total == Decimal('60.00')


def test_a_missed_weekly_charge_is_treated_as_a_skipped_session():
    # Last charge Nov 6; Nov 13 and 20 passed with nothing, Nov 27 still counts.
    rows = _charges(date(2026, 10, 30), date(2026, 11, 6))
    out = month_outlook([_bill(rows, 'weekly', '60.00')], date(2026, 11, 21))
    assert out.due_total == Decimal('60.00')


def test_a_weekly_bill_with_no_charge_left_this_month_is_paid():
    rows = _charges(date(2026, 11, 13), date(2026, 11, 20), date(2026, 11, 27))
    out = month_outlook([_bill(rows, 'weekly', '60.00')], date(2026, 11, 28))
    assert (out.paid_count, out.due_count) == (1, 0)
    assert out.due_total == 0


def test_a_biweekly_bill_steps_fourteen_days():
    # Last charge Nov 6: Nov 20 is past, so nothing remains this month...
    rows = _charges(date(2026, 10, 23), date(2026, 11, 6))
    out = month_outlook([_bill(rows, 'biweekly', '900.00')], date(2026, 11, 21))
    assert (out.paid_count, out.due_count) == (1, 0)
    # ...while on Nov 19 the Nov 20 charge is still ahead.
    out = month_outlook([_bill(rows, 'biweekly', '900.00')], date(2026, 11, 19))
    assert out.due_total == Decimal('900.00')


# ── quarterly ────────────────────────────────────────────────────────────────

def test_a_quarterly_bill_charged_on_the_first_is_due_three_calendar_months_on():
    """Oct 1 + 91 days is Dec 31; the bill is due Jan 1, not in December."""
    rows = _charges(date(2026, 4, 1), date(2026, 7, 1), date(2026, 10, 1),
                    amount='300.00')
    december = month_outlook([_bill(rows, 'quarterly', '300.00')], date(2026, 12, 15))
    assert (december.paid_count, december.due_count) == (0, 0)
    assert december.due_total == 0
    january = month_outlook([_bill(rows, 'quarterly', '300.00')], date(2027, 1, 5))
    assert (january.paid_count, january.due_count) == (0, 1)
    assert january.due_total == Decimal('300.00')


def test_an_overdue_quarterly_bill_is_still_due():
    rows = _charges(date(2026, 4, 1), date(2026, 7, 1))
    out = month_outlook([_bill(rows, 'quarterly', '300.00')], date(2026, 11, 2))
    assert out.due_count == 1


def test_a_quarterly_bill_charged_this_month_is_paid():
    rows = _charges(date(2026, 5, 10), date(2026, 8, 10), date(2026, 11, 10))
    out = month_outlook([_bill(rows, 'quarterly', '300.00')], date(2026, 11, 21))
    assert (out.paid_count, out.due_count) == (1, 0)


# ── which bills, and which charges ───────────────────────────────────────────

def test_bills_left_out_of_the_monthly_total_are_ignored():
    rows = _charges(date(2026, 10, 3), date(2026, 11, 3))
    bills = [_bill(rows, excluded=reason)
             for reason in ('inactive', 'annual', 'transfer')]
    out = month_outlook(bills, date(2026, 11, 21))
    assert (out.paid_count, out.due_count, out.paid_total) == (0, 0, 0)


def test_refunds_are_not_charges():
    rows = _charges(date(2026, 10, 3)) + [FakeTxn(date(2026, 11, 4), amount='-20.00')]
    out = month_outlook([_bill(rows)], date(2026, 11, 21))
    assert out.paid_total == 0
    assert out.due_count == 1


def test_paid_spend_is_only_the_charges_that_are_purchases():
    """Rent by Zelle (TRANSFER_OUT) and a loan payment are bills but not
    purchases; a utility autopay is both."""
    rent = _charges(date(2026, 10, 1), date(2026, 11, 1), amount='2000.00',
                    description='ZELLE PAYMENT TO LANDLORD', category='TRANSFER_OUT')
    loan = _charges(date(2026, 10, 5), date(2026, 11, 5), amount='310.00',
                    category='LOAN_PAYMENTS')
    power = _charges(date(2026, 10, 9), date(2026, 11, 9), amount='120.00',
                     category='RENT_AND_UTILITIES')
    out = month_outlook([_bill(rent), _bill(loan), _bill(power)], date(2026, 11, 21))
    assert out.paid_total == Decimal('2430.00')
    assert out.paid_spend == Decimal('120.00')
    assert (out.paid_count, out.count) == (3, 3)


def test_detection_supplies_the_occurrence_amount():
    """Through detect_recurring_with_rules: the typical charge is the P75
    figure monthly_amount is built from, before the cadence factor."""
    today = date(2026, 11, 21)
    rows = [FakeTxn(today - timedelta(days=7 * k), amount='60.00',
                    merchant_name='Tutor') for k in range(1, 9)]
    found = detect_recurring_with_rules(_group_transactions(rows), today, [])
    [bill] = found.bills
    assert bill['cadence'] == 'weekly'
    assert bill['occurrence_amount'] == Decimal('60.00')
    assert bill['monthly_amount'] == Decimal('260.00')   # 60 × 52/12
    out = month_outlook(found.bills, today)
    # Last charge Nov 14; Nov 21 (today) and Nov 28 are still to come.
    assert out.due_total == Decimal('120.00')


def test_a_rule_forced_monthly_stream_behaves_as_monthly():
    """A user rule asserting an irregular payment recurs makes a monthly
    stream: paid once anything posted this month, else due at its by-month
    typical figure."""
    from tests.test_recurring_rules import rule
    today = date(2026, 11, 21)
    # Irregular days, sometimes twice a month: no cadence is detected.
    dates = [date(2026, 6, 2), date(2026, 6, 20), date(2026, 7, 28),
             date(2026, 9, 1), date(2026, 9, 3), date(2026, 10, 17)]
    rows = [FakeTxn(d, amount='175.00', description='ACME TUITION 1234')
            for d in dates]
    found = detect_recurring_with_rules(
        _group_transactions(rows), today, [rule(pattern='ACME TUITION')])
    [bill] = found.bills
    assert bill['cadence_forced'] and bill['cadence'] == 'monthly'
    out = month_outlook(found.bills, today)
    assert (out.paid_count, out.due_count) == (0, 1)
    assert out.due_total == bill['occurrence_amount'] == Decimal('350.00')

    paid = rows + [FakeTxn(date(2026, 11, 4), amount='175.00',
                           description='ACME TUITION 1234')]
    found = detect_recurring_with_rules(
        _group_transactions(paid), today, [rule(pattern='ACME TUITION')])
    out = month_outlook(found.bills, today)
    assert (out.paid_count, out.due_count) == (1, 0)


def test_a_bill_paid_on_the_first_and_fifteenth_is_twice_a_month():
    """Its 13–17-day gaps make it biweekly, but it never charges a third time
    in a month: once both have posted, nothing is due."""
    rows = []
    for month in range(5, 12):
        rows += _charges(date(2026, month, 1), date(2026, month, 15), amount='500.00')
    bill = _bill(rows, 'biweekly', '500.00')
    for today in (date(2026, 11, 16), date(2026, 11, 28)):
        out = month_outlook([bill], today)
        assert (out.paid_count, out.due_count) == (1, 0), today
        assert out.paid_total == Decimal('1000.00')
    # Before the 15th, one charge is still to come.
    early = [t for t in rows if t.date < date(2026, 11, 15)]
    out = month_outlook([_bill(early, 'biweekly', '500.00')], date(2026, 11, 10))
    assert out.due_total == Decimal('500.00')


def test_a_true_biweekly_bill_can_charge_three_times_in_a_month():
    """Every other Friday from Jan 2: January and July hold three charges, so
    it is projected by its 14-day step — Oct 23 is still due on Oct 20."""
    start = date(2026, 1, 2)
    rows = _charges(*[start + timedelta(days=14 * k) for k in range(21)
                      if start + timedelta(days=14 * k) <= date(2026, 10, 16)],
                    amount='900.00')
    out = month_outlook([_bill(rows, 'biweekly', '900.00')], date(2026, 10, 20))
    assert out.due_total == Decimal('900.00')


def test_a_charge_dated_after_today_is_not_counted_yet():
    """The digest labels the charges "1st through today": a row dated later
    this month adds nothing to the paid total and does not pay the bill."""
    rows = _charges(date(2026, 9, 25), date(2026, 10, 25), date(2026, 11, 25))
    out = month_outlook([_bill(rows, occurrence='100.00')], date(2026, 11, 21))
    assert out.paid_total == 0
    assert (out.paid_count, out.due_count) == (0, 1)
    assert out.due_total == Decimal('100.00')
