"""Detection recall: weekly streams that skip sessions, Zelle payments that are
not transfers, and new monthly bills with only two charges so far.

All fixtures are fictional. Pure functions take a fixed `today` (knowledge
004); the route test freezes the clock and logs in inside the frozen block.
"""

import random
from datetime import date, timedelta
from decimal import Decimal
from types import SimpleNamespace

from freezegun import freeze_time

from app.bills import (
    _payment_status, detect_recurring_with_rules, fixed_monthly_total, mark_essential,
)
from app.models import Account, Institution, Transaction, db
from app.subscriptions import _build_stream, _classify_cadence

TODAY = date(2026, 6, 13)
FROZEN = '2026-06-13'


class Row:
    """A detection row: the columns `_DETECTION_COLUMNS` carries."""

    def __init__(self, d, amount, description, merchant_name=None,
                 category=None, category_detailed=None):
        self.date = d
        self.amount = Decimal(amount)
        self.description = description
        self.merchant_name = merchant_name
        self.merchant_entity_id = None
        self.institution_id = 1
        self.account_id = 'acc-1'
        self.removed = False
        self.category = category
        self.category_detailed = category_detailed


def detect(groups, rules=(), today=TODAY):
    return detect_recurring_with_rules(groups, today, list(rules))


def dates_from_gaps(last, gaps):
    """Dates ending on `last`, separated by `gaps` (oldest gap first)."""
    out = [last]
    for gap in reversed(gaps):
        out.append(out[-1] - timedelta(days=gap))
    return sorted(out)


def rows(dates, amount='40.00', description='MAPLE SPEECH STUDIO',
         merchant_name='Maple Speech Studio', **kwargs):
    return [Row(d, amount, description, merchant_name=merchant_name, **kwargs)
            for d in dates]


# A weekly appointment that skips a session now and then: one- and two-week
# skips are more than 30% of its gaps, so 7 ± 2 alone is not 70% regular.
SKIPPING_GAPS = [7, 14, 7, 21, 7, 14, 7, 7, 14, 21, 7]


def test_skipping_fixture_fails_the_plain_seven_day_test():
    within = sum(1 for g in SKIPPING_GAPS if abs(g - 7) <= 2)
    assert within / len(SKIPPING_GAPS) < 0.7


# --- 1. weekly skipped sessions --------------------------------------------

def test_a_weekly_appointment_that_skips_weeks_is_weekly():
    dates = dates_from_gaps(TODAY - timedelta(days=3), SKIPPING_GAPS)
    assert _classify_cadence(dates) == ('weekly', 7)
    [bill] = detect([rows(dates)]).bills
    assert (bill['cadence'], bill['active'], bill['excluded_reason']) == ('weekly', True, None)
    assert bill['monthly_amount'] == (Decimal('40.00') * 52 / 12).quantize(Decimal('0.01'))


def test_rescheduled_sessions_inside_a_week_still_fit():
    # Tuesday one week, Thursday the next, Tuesday after: 9 then 5 days.
    gaps = [7, 9, 5, 7, 14, 7, 9, 5, 7, 7]
    assert _classify_cadence(dates_from_gaps(TODAY, gaps)) == ('weekly', 7)


def test_an_irregular_merchant_with_gaps_up_to_25_days_is_still_rejected():
    # Median 8.5 lands in the weekly bucket, but under half the gaps fit
    # 7, 14 or 21 ± 2.
    gaps = [3, 10, 6, 25, 4, 17, 8, 2, 11, 9, 5, 24, 7, 13]
    assert _classify_cadence(dates_from_gaps(TODAY, gaps)) is None
    assert detect([rows(dates_from_gaps(TODAY, gaps))]).bills == []


def test_a_frequent_merchant_charged_every_few_days_is_still_rejected():
    gaps = [2, 5, 3, 10, 4, 2, 6, 3, 9, 2, 4, 8, 3, 5, 2, 10, 3]
    assert _classify_cadence(dates_from_gaps(TODAY, gaps)) is None


def test_random_three_to_fourteen_day_habits_rarely_pass_as_weekly():
    # A cafe or fuel stop visited every 3-14 days, on whatever weekday: the
    # skip allowance needs a kept weekday, so few such histories pass (about
    # 2% did before skips were allowed at all).
    rng = random.Random(20261108)
    passed = 0
    for _ in range(500):
        dates = [date(2026, 1, 1)]
        for _ in range(12):
            dates.append(dates[-1] + timedelta(days=rng.randint(3, 14)))
        passed += _classify_cadence(dates) == ('weekly', 7)
    assert passed / 500 < 0.06


def test_skips_need_the_appointment_to_keep_its_weekday():
    # The same skipping rhythm, but each charge nudged onto a different
    # weekday (-2..+2 days, gaps kept within their bands): no kept weekday,
    # so the skips are not allowed and the series fails 7 ± 2.
    base = dates_from_gaps(TODAY, SKIPPING_GAPS)
    shift = [0, 2, -1, 1, -2, 0, 2, -1, 1, -2, 0, 2]
    nudged = [d + timedelta(days=k) for d, k in zip(base, shift)]
    assert max(sum(1 for d in nudged if d.weekday() == w) for w in range(7)) / len(nudged) < 0.4
    assert _classify_cadence(sorted(nudged)) is None


def test_a_fourteen_day_median_is_still_biweekly():
    assert _classify_cadence(dates_from_gaps(TODAY, [14] * 8)) == ('biweekly', 14)
    assert _classify_cadence(dates_from_gaps(TODAY, [14, 14, 7, 14, 14, 21, 14, 14])) == (
        'biweekly', 14)


def test_other_buckets_do_not_accept_multiples():
    # Monthly with a skipped month (60 days) is still irregular, as before.
    gaps = [30, 60, 30, 60, 30, 60]
    assert _classify_cadence(dates_from_gaps(TODAY, gaps)) is None


def test_a_weekly_stream_stays_active_through_two_skipped_sessions():
    dates = dates_from_gaps(date(2026, 5, 1), [7] * 10)
    for overdue, active in [(10, True), (20, True), (23, True), (24, False)]:
        stream = _build_stream(rows(dates), dates[-1] + timedelta(days=overdue))
        assert stream['active'] is active, overdue


def test_a_weekly_bill_20_days_overdue_keeps_its_ordinary_payment_status():
    dates = dates_from_gaps(TODAY - timedelta(days=20), [7] * 10)
    group = rows(dates)
    [bill] = detect([group]).bills
    assert bill['active'] is True
    status, expected = _payment_status(group, TODAY)
    assert (bill['payment_status'], bill['expected_date_this_month']) == (status, expected)
    assert bill['excluded_reason'] is None


def test_non_weekly_streams_keep_one_and_a_half_cadences():
    dates = dates_from_gaps(date(2026, 1, 10), [14] * 6)
    assert _build_stream(rows(dates), dates[-1] + timedelta(days=21))['active'] is True
    assert _build_stream(rows(dates), dates[-1] + timedelta(days=22))['active'] is False


def test_weekly_income_that_skips_weeks_is_weekly_with_the_same_window():
    dates = dates_from_gaps(TODAY - timedelta(days=16), SKIPPING_GAPS)
    group = rows(dates, amount='-80.00', description='TUTORING CLIENT DEPOSIT',
                 merchant_name='Tutoring Client', category='INCOME')
    [income] = detect([group]).income
    assert (income['cadence'], income['active'], income['excluded_reason']) == (
        'weekly', True, None)


# --- 2. Zelle payments are not transfers ------------------------------------

def zelle(dates, payee='Jordan', category='TRANSFER_OUT',
          category_detailed='TRANSFER_OUT_ACCOUNT_TRANSFER'):
    return rows(dates, amount='40.00',
                description=f'{payee} PAYMENT ID ZZ000 ZELLE PAYMENT TO',
                merchant_name=None, category=category,
                category_detailed=category_detailed)


def test_a_regular_zelle_payment_is_a_counted_bill():
    dates = dates_from_gaps(TODAY - timedelta(days=2), SKIPPING_GAPS)
    [bill] = detect([zelle(dates)]).bills
    assert bill['excluded_reason'] is None
    assert fixed_monthly_total([bill])[1] == 1


def test_a_transfer_out_without_zelle_is_still_a_transfer():
    dates = dates_from_gaps(TODAY - timedelta(days=2), [7] * 10)
    group = rows(dates, description='ONLINE TO SAVINGS TRANSFER', merchant_name=None,
                 category='TRANSFER_OUT', category_detailed='TRANSFER_OUT_ACCOUNT_TRANSFER')
    [bill] = detect([group]).bills
    assert bill['excluded_reason'] == 'transfer'


def test_zelle_rows_vote_one_by_one_in_a_mixed_group():
    dates = dates_from_gaps(TODAY - timedelta(days=2), [7] * 10)
    mostly_zelle = zelle(dates[:8]) + rows(
        dates[8:], description='ONLINE TO SAVINGS TRANSFER', merchant_name=None,
        category='TRANSFER_OUT')
    [bill] = detect([mostly_zelle]).bills
    assert bill['excluded_reason'] is None
    mostly_transfer = zelle(dates[:3]) + rows(
        dates[3:], description='ONLINE TO SAVINGS TRANSFER', merchant_name=None,
        category='TRANSFER_OUT')
    [bill] = detect([mostly_transfer]).bills
    assert bill['excluded_reason'] == 'transfer'


def test_zelle_matches_any_case_but_only_as_a_word():
    dates = dates_from_gaps(TODAY - timedelta(days=2), [7] * 10)
    mixed_case = rows(dates, description='Jordan Zelle payment to', merchant_name=None,
                      category='TRANSFER_OUT')
    assert detect([mixed_case]).bills[0]['excluded_reason'] is None
    lookalike = rows(dates, description='GAZELLE SAVINGS XFER', merchant_name=None,
                     category='TRANSFER_OUT')
    assert detect([lookalike]).bills[0]['excluded_reason'] == 'transfer'


def test_a_zelle_deposit_is_not_income_evidence():
    # The Zelle vote is an outflow rule only: a Zelle deposit is still not income.
    dates = dates_from_gaps(TODAY - timedelta(days=2), [14] * 8)
    group = rows(dates, amount='-40.00', description='Jordan ZELLE PAYMENT FROM',
                 merchant_name=None, category='TRANSFER_IN')
    [income] = detect([group]).income
    assert income['excluded_reason'] == 'not income'


# --- 3. new monthly pairs ---------------------------------------------------

def activity(extra=(), amount='75.00', when=(date(2026, 4, 30), date(2026, 5, 31))):
    """A new kids' activity: optional odd first charge, then a fixed fee."""
    return [Row(d, a, 'HILLSIDE YOUTH SOCCER', merchant_name='Hillside Youth Soccer')
            for d, a in list(extra) + [(d, amount) for d in when]]


def test_a_pair_after_an_odd_first_charge_is_a_counted_new_bill():
    group = activity(extra=[(date(2026, 4, 9), '112.40')])
    assert _build_stream(group, TODAY) is None
    found = detect([group])
    [bill] = found.bills
    assert bill['name'] == 'Hillside Youth Soccer · $75.00'
    assert (bill['cadence'], bill['new'], bill['excluded_reason']) == ('monthly', True, None)
    assert bill['monthly_amount'] == Decimal('75.00')
    assert bill['essential_keys'] == ('merchant:hillside youth soccer@75.00',)
    assert found.suggestions == []


def test_pair_rows_never_feed_the_groups_suggestion():
    # Odd charges in two of the six months before June: no suggestion on
    # their own. Were the pair's April and May rows counted too, it would be
    # four months and the group would be suggested.
    odd = [(date(2026, 1, 5), '30.00'), (date(2026, 1, 26), '45.00'),
           (date(2026, 3, 20), '52.50')]
    group = activity(extra=odd)
    assert _build_stream(group, TODAY) is None
    found = detect([group])
    assert [b['new'] for b in found.bills] == [True]
    assert found.suggestions == []


def test_a_pair_across_the_new_year():
    group = activity(when=(date(2025, 12, 29), date(2026, 1, 28)))
    [bill] = detect([group], today=date(2026, 2, 3)).bills
    assert (bill['cadence'], bill['new']) == ('monthly', True)


def test_a_refund_does_not_make_a_whole_group_pair_an_in_group_plan():
    group = activity() + [Row(date(2026, 6, 2), '-10.00', 'HILLSIDE YOUTH SOCCER',
                              merchant_name='Hillside Youth Soccer')]
    [bill] = detect([group]).bills
    assert (bill['name'], bill['split_amount'], bill['new']) == (
        'Hillside Youth Soccer', None, True)
    assert bill['essential_keys'] == ('merchant:hillside youth soccer',)


def test_card_payments_and_transfers_are_never_new_pairs():
    for category, detailed in [('LOAN_PAYMENTS', 'LOAN_PAYMENTS_CREDIT_CARD_PAYMENT'),
                               ('TRANSFER_OUT', 'TRANSFER_OUT_ACCOUNT_TRANSFER')]:
        group = [Row(d, '500.00', 'CARD AUTOPAY', category=category,
                     category_detailed=detailed)
                 for d in (date(2026, 4, 30), date(2026, 5, 31))]
        found = detect([group])
        assert found.bills == [] and found.suggestions == [], category


def test_a_whole_group_pair_is_the_merchant_itself():
    [bill] = detect([activity()]).bills
    assert (bill['name'], bill['new'], bill['split_amount']) == (
        'Hillside Youth Soccer', True, None)
    assert bill['essential_keys'] == ('merchant:hillside youth soccer',)
    assert bill['excluded_reason'] is None


def test_a_third_charge_turns_the_pair_into_the_ordinary_stream_and_keeps_its_mark():
    saved = {detect([activity()]).bills[0]['essential_key']}
    later = activity(when=(date(2026, 4, 30), date(2026, 5, 31), date(2026, 6, 30)))
    [bill] = mark_essential(detect([later], today=date(2026, 7, 2)).bills, saved)
    assert (bill['name'], bill['new'], bill['count']) == ('Hillside Youth Soccer', False, 3)
    assert bill['essential'] is True


def test_pairs_that_do_not_look_like_a_new_monthly_bill_are_rejected():
    cases = {
        '18 days apart': (date(2026, 5, 20), date(2026, 6, 7)),
        'latest 50 days ago': (date(2026, 3, 24), date(2026, 4, 24)),
        'months not consecutive': (date(2026, 3, 31), date(2026, 5, 1)),
        'same month': (date(2026, 5, 1), date(2026, 5, 31)),
    }
    for label, when in cases.items():
        assert detect([activity(when=when)]).bills == [], label


def test_two_different_amounts_are_not_a_pair():
    group = [Row(date(2026, 4, 30), '75.00', 'HILLSIDE YOUTH SOCCER'),
             Row(date(2026, 5, 31), '80.00', 'HILLSIDE YOUTH SOCCER')]
    assert detect([group]).bills == []


def test_a_rule_claiming_the_pair_yields_only_the_rule_stream():
    rule = SimpleNamespace(id=7, label='Soccer', pattern='HILLSIDE YOUTH', direction='outflow',
                           amount_min=None, amount_max=None, action='recurring')
    found = detect([activity(extra=[(date(2026, 4, 9), '112.40')])], [rule])
    [bill] = found.bills
    assert (bill['name'], bill['rule_id'], bill['new']) == ('Soccer', 7, False)


def test_every_stream_carries_new():
    weekly = rows(dates_from_gaps(TODAY, [7] * 8), description='WEEKLY CLUB',
                  merchant_name='Weekly Club')
    found = detect([weekly, activity()])
    assert sorted(b['new'] for b in found.bills) == [False, True]


# --- the page ----------------------------------------------------------------

@freeze_time(FROZEN)
def test_page_badges_a_new_pair(client, app):
    with app.app_context():
        inst = Institution(name='Test Bank', slug='test_bank',
                           access_token='tok', item_id='item-1')
        db.session.add(inst)
        db.session.flush()
        db.session.add(Account(institution_id=inst.id, plaid_account_id='acc-1',
                               name='Checking', mask='9999'))
        for n, t in enumerate(activity(extra=[(date(2026, 4, 9), '112.40')])):
            db.session.add(Transaction(
                plaid_transaction_id=f'p-{n}', institution_id=inst.id,
                account_id='acc-1', date=t.date, description=t.description,
                merchant_name=t.merchant_name, amount=t.amount,
            ))
        db.session.commit()
    client.post('/login', data={'password': 'testpass'})
    html = client.get('/recurring').get_data(as_text=True)
    assert 'Hillside Youth Soccer · $75.00' in html
    assert 'new · 2 months' in html
