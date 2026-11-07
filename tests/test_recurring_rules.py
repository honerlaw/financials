"""User rules that correct /recurring (app/recurring_rules.py).

All fixtures are fictional. Pure functions use fixed dates (knowledge 004);
route tests freeze the clock and log in inside the frozen block, because
Flask's session cookie is timestamped.
"""

from datetime import date, timedelta
from decimal import Decimal
import re
from types import SimpleNamespace

import pytest
from freezegun import freeze_time

from app.bills import detect_recurring_with_rules, fixed_monthly_total
from app.models import Account, Institution, RecurringRule, Transaction, db
from app.recurring_rules import apply_rules, parse_rule_form, pattern_hint, preview
from app.subscriptions import merge_by_descriptor

TODAY = date(2026, 6, 13)


class Row:
    """A detection row: the columns `_DETECTION_COLUMNS` carries."""

    def __init__(self, d, amount, description, merchant_name=None,
                 category=None, category_detailed=None, merchant_entity_id=None):
        self.date = d
        self.amount = Decimal(amount)
        self.description = description
        self.merchant_name = merchant_name
        self.merchant_entity_id = merchant_entity_id
        self.institution_id = 1
        self.account_id = 'acc-1'
        self.removed = False
        self.category = category
        self.category_detailed = category_detailed

    def __repr__(self):
        return f'Row({self.date}, {self.amount}, {self.description!r})'


def rule(id=1, label='My rule', pattern='ACME', direction='outflow',
         amount_min=None, amount_max=None, action='recurring'):
    return SimpleNamespace(
        id=id, label=label, pattern=pattern, direction=direction,
        amount_min=None if amount_min is None else Decimal(amount_min),
        amount_max=None if amount_max is None else Decimal(amount_max),
        action=action,
    )


def monthly(description, amount, n=5, day=10, start=(2026, 1), **kwargs):
    rows = []
    year, month = start
    for _ in range(n):
        rows.append(Row(date(year, month, day), amount, description, **kwargs))
        month += 1
        if month > 12:
            year, month = year + 1, 1
    return rows


def checks():
    """One mixed check group: a fictional payee paid 300–320 monthly, plus
    other checks of unrelated amounts."""
    payee = [Row(date(2026, m, 3 + m), a, f'Check #{1000 + m}')
             for m, a in zip(range(1, 6), ('300.00', '305.00', '310.00', '315.00', '320.00'))]
    others = [Row(date(2026, 1, 20), '45.00', 'Check #2001'),
              Row(date(2026, 3, 22), '1200.00', 'Check #2002'),
              Row(date(2026, 4, 2), '90.00', 'Check #2003')]
    return payee, others


# ── apply_rules ──────────────────────────────────────────────────────────────

def test_matches_case_insensitive_substring_of_raw_description():
    rows = [Row(TODAY, '10.00', 'Acme Utilities 0042'), Row(TODAY, '10.00', 'Other')]
    result = apply_rules([rows], [rule(pattern='acme util')])
    assert result.claims[0].rows == [rows[0]]
    assert result.groups == [[rows[1]]]


def test_direction_never_claims_the_other_sign():
    out_row = Row(TODAY, '50.00', 'TRANSFER TO ****1234')
    in_row = Row(TODAY, '-50.00', 'TRANSFER FROM ****1234')
    zero = Row(TODAY, '0.00', 'TRANSFER ****1234')
    group = [out_row, in_row, zero]
    outflow = apply_rules([group], [rule(pattern='****1234', direction='outflow')])
    inflow = apply_rules([group], [rule(pattern='****1234', direction='inflow')])
    assert outflow.claims[0].rows == [out_row]
    assert outflow.groups == [[in_row, zero]]
    assert inflow.claims[0].rows == [in_row]
    assert inflow.groups == [[out_row, zero]]


@pytest.mark.parametrize('amount_min, amount_max, claimed', [
    ('300.00', '320.00', 5),     # inclusive at both ends
    ('300.01', '319.99', 3),
    ('300.00', None, 6),         # min only: also the 1200 check
    (None, '100.00', 2),         # max only: the 45 and 90 checks
])
def test_inclusive_abs_amount_range(amount_min, amount_max, claimed):
    payee, others = checks()
    result = apply_rules([payee + others], [rule(pattern='Check',
                                                 amount_min=amount_min,
                                                 amount_max=amount_max)])
    assert len(result.claims[0].rows) == claimed


def test_inflow_range_compares_magnitude():
    deposits = [Row(TODAY, '-250.00', 'ACME PAY'), Row(TODAY, '-900.00', 'ACME PAY')]
    result = apply_rules([deposits], [rule(direction='inflow', amount_max='300')])
    assert result.claims[0].rows == [deposits[0]]


def test_range_beats_longer_pattern_even_half_open():
    payee, others = checks()
    long_no_range = rule(id=1, label='long', pattern='Check #10')
    half_open = rule(id=2, label='ranged', pattern='Check', amount_min='300')
    result = apply_rules([payee + others], [long_no_range, half_open])
    assert len(result.claims[1].rows) == 6          # every row of 300 or more
    assert result.claims[0].rows == []


def test_longer_pattern_then_lower_id_breaks_ties():
    rows = [Row(TODAY, '20.00', 'ACME STREAMING PLUS')]
    short, long_ = rule(id=1, pattern='ACME'), rule(id=2, pattern='ACME STREAMING')
    assert apply_rules([rows], [short, long_]).claims[1].rows == rows
    older, newer = rule(id=3, pattern='STREAM'), rule(id=4, pattern='STREAM')
    result = apply_rules([rows], [newer, older])
    assert result.claims[1].rows == rows and result.claims[0].rows == []


def test_claimed_rows_leave_their_groups_and_empty_groups_are_dropped():
    a = monthly('ACME BILL', '40.00')
    b = monthly('Other Shop', '12.00')
    result = apply_rules([a, b], [rule(pattern='ACME BILL')])
    assert result.groups == [b]
    assert result.claims[0].rows == a


def test_identical_same_day_rows_are_both_claimed():
    twins = [Row(TODAY, '25.00', 'ACME'), Row(TODAY, '25.00', 'ACME')]
    other = Row(TODAY, '25.00', 'Elsewhere')
    result = apply_rules([twins + [other]], [rule()])
    assert len(result.claims[0].rows) == 2
    assert result.groups == [[other]]


def test_value_equal_rows_are_partitioned_by_position():
    """Production rows are SQLAlchemy Rows, which compare by value: two
    identical same-day rows must both be claimed, or both kept."""
    from collections import namedtuple
    Plain = namedtuple('Plain', 'date amount description merchant_name')
    twin = lambda: Plain(TODAY, Decimal('25.00'), 'ACME', None)
    kept_twin = lambda: Plain(TODAY, Decimal('25.00'), 'Elsewhere', None)
    group = [twin(), twin(), kept_twin(), kept_twin()]
    result = apply_rules([group], [rule()])
    assert len(result.claims[0].rows) == 2
    assert result.groups == [[kept_twin(), kept_twin()]]
    assert len(result.groups[0]) == 2


def test_records_rows_won_and_n_of_m_per_source_group():
    payee, others = checks()
    result = apply_rules([payee + others], [rule(pattern='Check', amount_min='300',
                                                 amount_max='320')])
    [source] = result.claims[0].sources
    assert (source['name'], source['taken'], source['total']) == ('Check #1001', 5, 8)
    assert source['amount_low'] == Decimal('300.00')
    assert source['amount_high'] == Decimal('320.00')


def test_rule_matching_nothing_claims_nothing():
    group = monthly('Other Shop', '12.00')
    result = apply_rules([group], [rule(pattern='NOTHING HERE')])
    assert result.claims[0].rows == [] and result.claims[0].sources == []
    assert result.groups == [group]


def test_input_is_not_mutated():
    payee, others = checks()
    group = payee + others
    snapshot = list(group)
    apply_rules([group], [rule(pattern='Check', amount_min='300')])
    assert group == snapshot


def test_result_is_independent_of_group_and_rule_order():
    a, b = monthly('ACME BILL', '40.00'), monthly('ACME BILLING CO', '15.00')
    rules = [rule(id=1, pattern='ACME'), rule(id=2, pattern='BILLING')]
    forward = apply_rules([a, b], rules)
    backward = apply_rules([b, a], list(reversed(rules)))
    by_id = lambda res: {c.rule.id: c.rows for c in res.claims}
    assert by_id(forward) == by_id(backward)
    assert sorted(map(len, forward.groups)) == sorted(map(len, backward.groups))


def test_pattern_and_range_take_one_payee_out_of_a_check_group():
    payee, others = checks()
    result = apply_rules([payee + others], [rule(pattern='Check', amount_min='295',
                                                 amount_max='330')])
    assert result.claims[0].rows == payee
    assert result.groups == [others]


# ── preview ──────────────────────────────────────────────────────────────────

def test_preview_reports_rows_lost_to_and_taken_from_saved_rules():
    payee, others = checks()
    groups = [payee + others]
    saved = [rule(id=1, label='Saved ranged', pattern='Check', amount_min='300',
                  amount_max='320')]
    broad = rule(id=None, label='Candidate', pattern='Check')
    lost = preview(groups, saved, broad)
    assert lost['won'] == 3
    assert lost['lost'] == [{'label': 'Saved ranged', 'pattern': 'Check', 'rows': 5}]

    saved = [rule(id=1, label='Saved broad', pattern='Check')]
    ranged = rule(id=None, pattern='Check', amount_min='300', amount_max='320')
    taken = preview(groups, saved, ranged)
    assert taken['won'] == 5
    assert taken['taken'] == [{'label': 'Saved broad', 'pattern': 'Check', 'rows': 5}]
    assert taken['lost'] == []


def test_unsaved_candidate_ranks_after_saved_rules():
    rows = [Row(TODAY, '20.00', 'ACME')]
    result = preview([rows], [rule(id=7, label='Saved')], rule(id=None, label='New'))
    assert result['won'] == 0
    assert result['lost'] == [{'label': 'Saved', 'pattern': 'ACME', 'rows': 1}]


def test_preview_keeps_saved_rules_with_the_same_label_apart():
    rows = [Row(TODAY, '20.00', 'ACME ONE'), Row(TODAY, '20.00', 'ACME TWO')]
    saved = [rule(id=1, label='Dup', pattern='ACME ONE'),
             rule(id=2, label='Dup', pattern='ACME TWO')]
    result = preview([rows], saved, rule(id=None, pattern='ACME'))
    assert [t['pattern'] for t in result['lost']] == ['ACME ONE', 'ACME TWO']


# ── pattern hint ─────────────────────────────────────────────────────────────

@pytest.mark.parametrize('descriptions, hint', [
    (['Check #1234', 'Check #1301'], 'Check'),
    (['TRANSFER TO ****1234', 'TRANSFER TO ****5678'], 'TRANSFER TO'),
    (['ACME UTILITIES'], 'ACME UTILITIES'),
    (['AB 12', 'AC 13', 'AB 12'], 'AB 12'),      # prefix too short: most common
])
def test_pattern_hint(descriptions, hint):
    assert pattern_hint([Row(TODAY, '1.00', d) for d in descriptions]) == hint


# ── form parsing ─────────────────────────────────────────────────────────────

def test_parse_rule_form_accepts_a_valid_rule():
    fields, errors = parse_rule_form({
        'label': ' Payee ', 'pattern': ' Check ', 'direction': 'outflow',
        'action': 'recurring', 'amount_min': '$1,050', 'amount_max': '1100.5',
    })
    assert errors == []
    assert fields['label'] == 'Payee' and fields['pattern'] == 'Check'
    assert fields['amount_min'] == Decimal('1050.00')
    assert fields['amount_max'] == Decimal('1100.50')


def test_parse_rule_form_requires_direction_and_action_unless_defaulted():
    _, errors = parse_rule_form({'label': 'X', 'pattern': 'ACME'})
    assert 'Choose money out or money in.' in errors
    assert 'Choose recurring or not recurring.' in errors
    fields, errors = parse_rule_form({'label': 'X', 'pattern': 'ACME'}, defaults=True)
    assert errors == [] and (fields['direction'], fields['action']) == ('outflow', 'recurring')


def test_parse_rule_form_strips_control_characters():
    """Postgres rejects NUL in text; SQLite would store it."""
    fields, errors = parse_rule_form({'label': 'A\x00B', 'pattern': '\x00ab\x00',
                                      'direction': 'outflow', 'action': 'recurring'})
    assert fields['label'] == 'AB' and fields['pattern'] == 'ab'
    assert any('at least 3 characters' in e for e in errors)


@pytest.mark.parametrize('text', ['0', '-0', '0.00'])
def test_minimum_of_zero_is_no_range(text):
    fields, errors = parse_rule_form({'label': 'X', 'pattern': 'ACME', 'amount_min': text,
                                      'direction': 'outflow', 'action': 'recurring'})
    assert errors == [] and fields['amount_min'] is None


# ── detection ────────────────────────────────────────────────────────────────

def _detect(groups, rules):
    return detect_recurring_with_rules(groups, TODAY, rules)


def _bill(found, name):
    [bill] = [b for b in found.bills if b['name'] == name]
    return bill


def test_recurring_rule_counts_transfer_categorized_bill():
    rows = monthly('ACME LOAN PMT', '400.00', start=(2026, 2),
                   category='TRANSFER_OUT', category_detailed='TRANSFER_OUT_ACCOUNT_TRANSFER')
    assert _detect([rows], []).bills[0]['excluded_reason'] == 'transfer'
    found = _detect([rows], [rule(label='Loan', pattern='ACME LOAN')])
    bill = _bill(found, 'Loan')
    assert bill['excluded_reason'] is None
    assert bill['monthly_amount'] == Decimal('400.00')
    assert bill['rule_id'] == 1
    assert found.rules[0]['status'] == 'counted'


def test_irregular_outflows_under_a_recurring_rule_count_as_monthly():
    days = [date(2026, 3, 2), date(2026, 3, 29), date(2026, 5, 20), date(2026, 6, 1)]
    rows = [Row(d, '80.00', 'ACME SERVICE') for d in days]
    assert _detect([rows], []).bills == []
    bill = _bill(_detect([rows], [rule(label='Service')]), 'Service')
    assert (bill['cadence'], bill['cadence_forced']) == ('monthly', True)
    assert bill['excluded_reason'] is None


def test_forced_monthly_split_payments_are_estimated_from_monthly_totals():
    """Two irregular parts a month: one part (P75 of dates) would understate it."""
    pairs = [(1, 3, 21), (2, 6, 25), (3, 2, 17), (4, 9, 28), (5, 4, 19), (6, 1, 11)]
    rows = []
    for month, first, second in pairs:
        rows.append(Row(date(2026, month, first), '100.00', 'ACME PLAN'))
        rows.append(Row(date(2026, month, second), '150.00', 'ACME PLAN'))
    bill = _bill(_detect([rows], [rule(label='Plan')]), 'Plan')
    assert bill['cadence_forced'] is True
    assert bill['monthly_amount'] == Decimal('250.00')


def test_forced_monthly_estimate_never_falls_below_one_payment():
    """Monthly totals' P75 can sit below the per-date P75 (one heavy month of
    several payments, several light months); the estimate takes the larger."""
    rows = [Row(date(2026, m, d), '100.00', 'ACME PLAN')
            for m, d in ((1, 3), (2, 17), (3, 9), (4, 26))]
    rows += [Row(date(2026, 5, d), '300.00', 'ACME PLAN') for d in (2, 12, 22)]
    bill = _bill(_detect([rows], [rule(label='Plan')]), 'Plan')
    assert bill['cadence_forced'] is True
    assert bill['monthly_amount'] == Decimal('300.00')


def test_forced_monthly_bill_is_never_unpaid():
    """An irregular stream has no due day: paid once anything posts this
    month, otherwise upcoming."""
    days = [date(2026, 2, 2), date(2026, 3, 1), date(2026, 4, 26), date(2026, 5, 3)]
    rows = [Row(d, '80.00', 'ACME SERVICE') for d in days]
    found = _detect([rows], [rule(label='Service')])
    assert _bill(found, 'Service')['payment_status'] == 'upcoming'
    rows.append(Row(date(2026, 6, 2), '80.00', 'ACME SERVICE'))
    found = _detect([rows], [rule(label='Service')])
    assert _bill(found, 'Service')['payment_status'] == 'paid'


def test_outflow_rule_leaves_matching_inflows_in_their_group():
    bills_out = monthly('ACME TRANSFER ****1234', '300.00', start=(2026, 2))
    back_in = monthly('ACME TRANSFER ****1234', '-300.00', start=(2026, 2), day=20,
                      category='INCOME', category_detailed='INCOME_OTHER')
    found = _detect([bills_out + back_in], [rule(label='Bill', pattern='****1234')])
    assert _bill(found, 'Bill')['excluded_reason'] is None
    assert [s['name'] for s in found.income] == ['ACME TRANSFER ****1234']
    assert found.income[0]['rule_id'] is None
    assert found.rules[0]['rows_won'] == 5


def test_inflow_rule_counts_uncategorized_regular_income():
    deposits = monthly('ACME RENTAL INCOME', '-1500.00', start=(2026, 2))
    assert _detect([deposits], []).income[0]['excluded_reason'] == 'not income'
    found = _detect([deposits], [rule(label='Rent in', pattern='RENTAL',
                                      direction='inflow')])
    [stream] = found.income
    assert (stream['name'], stream['excluded_reason']) == ('Rent in', None)
    assert stream['monthly_amount'] == Decimal('1500.00')


def test_irregular_inflows_under_an_inflow_rule_are_not_counted():
    days = [date(2026, 1, 5), date(2026, 3, 29), date(2026, 4, 3), date(2026, 6, 2)]
    deposits = [Row(d, '-500.00', 'ACME SIDE GIG') for d in days]
    found = _detect([deposits], [rule(label='Gig', pattern='SIDE GIG', direction='inflow')])
    assert found.income == []
    assert found.rules[0]['status'] == 'no regular cadence'


def test_inactive_recurring_rule_outflow_is_not_counted():
    rows = monthly('ACME OLD LOAN', '200.00', start=(2025, 6))
    found = _detect([rows], [rule(label='Old loan', pattern='OLD LOAN')])
    assert _bill(found, 'Old loan')['excluded_reason'] == 'inactive'
    assert found.rules[0]['status'] == 'not counted: inactive'


def test_annual_rows_under_a_recurring_rule_stay_annual():
    rows = [Row(date(y, 4, 15), '120.00', 'ACME DOMAIN') for y in (2024, 2025, 2026)]
    bill = _bill(_detect([rows], [rule(label='Domain', pattern='DOMAIN')]), 'Domain')
    assert (bill['cadence'], bill['cadence_forced']) == ('annual', False)
    assert bill['excluded_reason'] == 'annual'


def test_not_recurring_rule_removes_a_counted_bill_and_lists_it_as_marked():
    gym = monthly('ACME GYM', '60.00', start=(2026, 2), merchant_name='Acme Gym')
    other = monthly('Electric Co', '90.00', start=(2026, 2))
    assert {b['name'] for b in _detect([gym, other], []).bills} == {'Acme Gym', 'Electric Co'}
    found = _detect([gym, other], [rule(label='Not a bill', pattern='ACME GYM',
                                        action='not_recurring')])
    assert [b['name'] for b in found.bills] == ['Electric Co']
    assert fixed_monthly_total(found.bills) == (Decimal('90.00'), 1)
    [marked] = found.marked
    assert marked['label'] == 'Not a bill' and marked['rows_won'] == 5
    assert [s['name'] for s in marked['sources']] == ['Acme Gym']


def test_claiming_rows_can_change_how_leftover_groups_merge():
    """A one-off row inside the renamed group's span stops the rename merge;
    once a rule claims it, the two groups are sequential and merge."""
    old = [Row(date(2026, m, 5), '30.00', 'CONTOSO SVC', merchant_name='Contoso Old')
           for m in (1, 2, 3)]
    new = [Row(date(2026, m, 5), '30.00', 'CONTOSO SVC', merchant_name='Contoso')
           for m in (4, 5, 6)]
    new.append(Row(date(2026, 2, 20), '75.00', 'CONTOSO SVC ONEOFF', merchant_name='Contoso'))
    assert len(merge_by_descriptor([old, new])) == 2
    leftover = apply_rules([old, new], [rule(pattern='ONEOFF', action='not_recurring')]).groups
    assert len(merge_by_descriptor(leftover)) == 1


def test_claiming_rows_can_change_a_leftover_groups_dominant_descriptor():
    """Promo rows outnumber the renamed group's own descriptor, so it does not
    share the old group's descriptor; once a rule claims them, it does."""
    old = [Row(date(2026, m, 5), '30.00', 'CONTOSO SVC', merchant_name='Contoso Old')
           for m in (1, 2, 3)]
    new = [Row(date(2026, m, 5), '30.00', 'CONTOSO SVC', merchant_name='Contoso')
           for m in (4, 5, 6)]
    new += [Row(date(2026, m, 15), '5.00', 'CONTOSO PROMO', merchant_name='Contoso')
            for m in (4, 5, 6, 6)]
    assert len(merge_by_descriptor([old, new])) == 2
    leftover = apply_rules([old, new], [rule(pattern='PROMO', action='not_recurring')]).groups
    assert len(merge_by_descriptor(leftover)) == 1


# ── routes ───────────────────────────────────────────────────────────────────

FROZEN = '2026-06-13'


def _seed(app):
    """A fictional bank with a monthly bill, a mixed check group and a regular
    transfer-categorized payment, dated around the frozen today."""
    with app.app_context():
        inst = Institution(name='Test Bank', slug='test_bank',
                           access_token='tok', item_id='item-1')
        db.session.add(inst)
        db.session.flush()
        db.session.add(Account(institution_id=inst.id, plaid_account_id='acc-1',
                               name='Checking', mask='9999'))
        n = 0

        def add(d, amount, description, **kwargs):
            nonlocal n
            n += 1
            db.session.add(Transaction(
                plaid_transaction_id=f'r-{n}', institution_id=inst.id,
                account_id='acc-1', date=d, description=description,
                amount=Decimal(amount), **kwargs,
            ))

        for month in range(1, 7):
            add(date(2026, month, 10), '95.00', 'Electric Co', merchant_name='Electric Co')
            add(date(2026, month, 4), '310.00', f'Check #{1000 + month}')
            add(date(2026, month, 2), '400.00', 'ACME LOAN PMT',
                category='TRANSFER_OUT', category_detailed='TRANSFER_OUT_ACCOUNT_TRANSFER')
        # Other checks written the same day as the payee's, so the mixed
        # group is still detected as one monthly stream (with a Flag link).
        add(date(2026, 2, 4), '45.00', 'Check #2001')
        add(date(2026, 4, 4), '1200.00', 'Check #2002')
        db.session.commit()


def _login(client):
    client.post('/login', data={'password': 'testpass'})


def _add_rule(app, **kwargs):
    with app.app_context():
        values = dict(label='Payee', pattern='Check', direction='outflow',
                      action='recurring', amount_min=Decimal('300'),
                      amount_max=Decimal('320'))
        values.update(kwargs)
        db.session.add(RecurringRule(**values))
        db.session.commit()


VALID = {'label': 'Payee', 'pattern': 'Check', 'direction': 'outflow',
         'action': 'recurring', 'amount_min': '300', 'amount_max': '320'}


@freeze_time(FROZEN)
def test_create_rule_saves_and_redirects(client, app):
    _login(client)
    res = client.post('/recurring/rules', data=VALID)
    assert res.status_code == 302 and res.headers['Location'].endswith('/recurring')
    with app.app_context():
        [saved] = RecurringRule.query.all()
        assert (saved.label, saved.pattern, saved.amount_min) == ('Payee', 'Check', Decimal('300.00'))


@pytest.mark.parametrize('change, message', [
    ({'label': '  '}, 'Give the rule a name'),
    ({'pattern': ' ab '}, 'at least 3 characters'),
    ({'action': 'maybe'}, 'Choose recurring or not recurring'),
    ({'direction': 'sideways'}, 'Choose money out or money in'),
    ({'direction': ''}, 'Choose money out or money in'),
    ({'action': ''}, 'Choose recurring or not recurring'),
    ({'amount_min': 'abc'}, 'Minimum amount must be a number'),
    ({'amount_min': 'NaN'}, 'Minimum amount must be a number'),
    ({'amount_max': '-5'}, 'cannot be negative'),
    ({'amount_min': '400', 'amount_max': '300'}, 'minimum amount is larger'),
])
@freeze_time(FROZEN)
def test_invalid_rule_rerenders_with_an_error_and_saves_nothing(client, app, change, message):
    _login(client)
    res = client.post('/recurring/rules', data={**VALID, **change})
    assert res.status_code == 400
    assert message in res.get_data(as_text=True)
    with app.app_context():
        assert RecurringRule.query.count() == 0


@freeze_time(FROZEN)
def test_preview_lists_the_rows_a_rule_would_claim(client, app):
    _seed(app)
    _login(client)
    res = client.get('/recurring/rules/new', query_string={**VALID, 'preview': '1'})
    html = res.get_data(as_text=True)
    assert res.status_code == 200
    assert 'This rule would claim 6 transactions' in html
    assert '6 of 8 rows' in html


@freeze_time(FROZEN)
def test_preview_shows_rows_lost_to_a_saved_rule(client, app):
    _seed(app)
    _add_rule(app, label='Saved payee')
    _login(client)
    res = client.get('/recurring/rules/new', query_string={
        **VALID, 'amount_min': '', 'amount_max': '', 'preview': '1'})
    html = res.get_data(as_text=True)
    assert 'This rule would claim 2 transactions' in html
    assert '6 matching transactions stay with your rule "Saved payee" ("Check")' in html


@freeze_time(FROZEN)
def test_preview_shows_rows_taken_from_a_saved_rule(client, app):
    _seed(app)
    _add_rule(app, label='All checks', amount_min=None, amount_max=None)
    _login(client)
    html = client.get('/recurring/rules/new', query_string={**VALID, 'preview': '1'}).get_data(as_text=True)
    assert 'This rule would claim 6 transactions' in html
    assert 'It would take 6 from your rule "All checks" ("Check")' in html


@freeze_time(FROZEN)
def test_preview_works_without_a_name(client, app):
    _seed(app)
    _login(client)
    html = client.get('/recurring/rules/new', query_string={
        'pattern': 'Check', 'preview': '1'}).get_data(as_text=True)
    assert 'This rule would claim 8 transactions' in html
    assert 'formnovalidate' in html


@freeze_time(FROZEN)
def test_delete_removes_the_rule(client, app):
    _add_rule(app)
    _login(client)
    with app.app_context():
        rule_id = RecurringRule.query.one().id
    res = client.post(f'/recurring/rules/{rule_id}/delete')
    assert res.status_code == 302
    with app.app_context():
        assert RecurringRule.query.count() == 0


@pytest.mark.parametrize('method, path', [
    ('get', '/recurring/rules/new'),
    ('post', '/recurring/rules'),
    ('post', '/recurring/rules/1/delete'),
])
def test_rule_routes_require_login(client, app, method, path):
    res = getattr(client, method)(path)
    assert res.status_code == 302 and '/login' in res.headers['Location']
    with app.app_context():
        assert RecurringRule.query.count() == 0


def _href_for(html, name):
    """The Flag href on the row whose name cell starts with `name`."""
    match = re.search(r'<td class="medium">\s*' + re.escape(name) +
                      r'\s*<a class="xs muted" href="([^"]+)">Flag</a>', html)
    assert match, f'no Flag link for {name}'
    return match.group(1).replace('&amp;', '&')


@freeze_time(FROZEN)
def test_flag_link_carries_pattern_hint_and_direction(client, app):
    _seed(app)
    _login(client)
    html = client.get('/recurring').get_data(as_text=True)
    href = _href_for(html, 'Check #1001')
    assert 'pattern=Check&' in href and 'direction=outflow' in href
    form = client.get(href).get_data(as_text=True)
    assert 'value="Check"' in form
    assert 'This rule would claim 8 transactions' in form


@freeze_time(FROZEN)
def test_add_a_rule_defaults_to_money_out(client, app):
    _login(client)
    html = client.get('/recurring').get_data(as_text=True)
    assert '/recurring/rules/new"' in html
    form = client.get('/recurring/rules/new').get_data(as_text=True)
    assert re.search(r'value="outflow"\s+checked', form)
    assert 'Give the rule a name' not in form    # arriving is not a failed submit


@freeze_time(FROZEN)
def test_rules_card_badge_and_counted_rule_bill(client, app):
    _seed(app)
    _add_rule(app)                                            # the 310 checks
    _add_rule(app, label='Car', pattern='ACME LOAN', amount_min=None, amount_max=None)
    _add_rule(app, label='Nothing', pattern='ZZZ NOTHING', amount_min=None, amount_max=None)
    _login(client)
    html = client.get('/recurring').get_data(as_text=True)
    counted = html.split('Counted expenses', 1)[1].split('Not counted', 1)[0]
    assert re.search(r'Payee\s*<span class="badge badge-accent">your rule</span>', counted)
    assert re.search(r'Car\s*<span class="badge badge-accent">your rule</span>', counted)
    assert '3 expenses' in html
    rules_card = html.split('Your rules', 1)[1]
    assert 'Jun 04, 2026' in rules_card                     # Payee's last matched
    assert '0 rows' in rules_card                           # Nothing
    assert 'Check #1001 (6 of 8 rows)' in rules_card


@freeze_time(FROZEN)
def test_marked_not_recurring_renders_as_the_only_not_counted_group(client, app):
    _seed(app)
    _add_rule(app, label='Not a bill', pattern='Electric', action='not_recurring',
              amount_min=None, amount_max=None)
    _add_rule(app, label='Car', pattern='ACME LOAN', amount_min=None, amount_max=None)
    _add_rule(app, label='Checks', pattern='Check', action='not_recurring',
              amount_min=None, amount_max=None)
    _login(client)
    html = client.get('/recurring').get_data(as_text=True)
    not_counted = html.split('Not counted', 1)[1].split('Recurring income</div>', 1)[0]
    assert 'Marked not recurring (2)' in not_counted
    assert 'Transfers (' not in not_counted and 'Inactive (' not in not_counted
    assert 'Electric Co (6 of 6 rows)' in not_counted


def test_session_cookie_is_samesite_lax(client):
    res = client.post('/login', data={'password': 'testpass'})
    assert 'SameSite=Lax' in res.headers['Set-Cookie']


def test_page_query_count_does_not_grow_with_rules(app):
    """Rules are read as plain rows: the commit after detection cannot expire
    them into one re-SELECT each when the card renders."""
    from tests.test_merchant_groups import _count_selects, _seed_page_corpus
    counts = []
    for n_rules in (1, 10):
        with app.app_context():
            db.drop_all()
            db.create_all()
            _seed_page_corpus(5)
            for i in range(n_rules):
                db.session.add(RecurringRule(label=f'Rule {i}', pattern=f'zz{i}zz',
                                             direction='outflow', action='recurring'))
            db.session.commit()
            client = app.test_client()
            client.post('/login', data={'password': 'testpass'})
            db.session.expunge_all()
            response, selects = _count_selects(lambda: client.get('/recurring'))
            assert response.status_code == 200
            counts.append(selects)
    assert counts[0] == counts[1], counts
