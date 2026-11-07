"""Same-amount sub-streams and "Possibly recurring" suggestions (app/bills.py).

All fixtures are fictional. Pure functions use fixed dates (knowledge 004);
route tests freeze the clock and log in inside the frozen block, because
Flask's session cookie is timestamped.
"""

from datetime import date, timedelta
import re
from decimal import Decimal
from types import SimpleNamespace

from freezegun import freeze_time

from app.bills import detect_recurring_with_rules, fixed_monthly_total
from app.models import Account, Institution, Transaction, db
from app.subscriptions import _build_stream

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

    def __repr__(self):
        return f'Row({self.date}, {self.amount}, {self.description!r})'


def rule(id=1, label='My rule', pattern='EXAMPLE', direction='outflow',
         amount_min=None, amount_max=None, action='recurring'):
    return SimpleNamespace(
        id=id, label=label, pattern=pattern, direction=direction,
        amount_min=None if amount_min is None else Decimal(amount_min),
        amount_max=None if amount_max is None else Decimal(amount_max),
        action=action,
    )


def series(day, amount, description, months, year=2026, **kwargs):
    return [Row(date(year, m, day), amount, description, **kwargs) for m in months]


def two_plans(sign='', **kwargs):
    """Two fixed-price plans at one merchant, billed on the 3rd and the 25th."""
    return (
        series(3, f'{sign}9.00', 'EXAMPLE CO BASIC', range(1, 7),
               merchant_name='Example Co', **kwargs)
        + series(25, f'{sign}14.00', 'EXAMPLE CO PLUS', range(1, 6),
                 merchant_name='Example Co', **kwargs)
    )


# Charged on varying days at varying amounts in Jan, Feb, Mar and May.
_VISITS = [
    (date(2026, 1, 7), '120.00'), (date(2026, 1, 21), '95.00'),
    (date(2026, 2, 11), '140.00'),
    (date(2026, 3, 4), '120.00'), (date(2026, 3, 25), '110.00'),
    (date(2026, 5, 13), '160.00'),
]


def visits(drop_months=(), extra=(), name='Riverside Therapy', **kwargs):
    rows = [(d, a) for d, a in _VISITS if d.month not in drop_months] + list(extra)
    return [Row(d, a, f'{name.upper()} {d:%m%d}', merchant_name=name, **kwargs)
            for d, a in rows]


def detect(groups, rules=()):
    return detect_recurring_with_rules(groups, TODAY, list(rules))


def names(bills):
    return sorted(b['name'] for b in bills)


# --- the split ---------------------------------------------------------------

def test_two_plans_at_one_merchant_become_two_monthly_streams():
    group = two_plans()
    assert _build_stream(group, TODAY) is None
    bills = detect([group]).bills
    assert names(bills) == ['Example Co · $14.00', 'Example Co · $9.00']
    assert {b['cadence'] for b in bills} == {'monthly'}
    assert {b['excluded_reason'] for b in bills} == {None}
    by_amount = {b['split_amount']: b for b in bills}
    assert by_amount[Decimal('9.00')]['monthly_amount'] == Decimal('9.00')
    assert by_amount[Decimal('14.00')]['monthly_amount'] == Decimal('14.00')


def test_a_group_detected_as_a_whole_is_not_split():
    # A monthly bill whose price changed once: detected whole, never split.
    group = (series(10, '20.00', 'ELECTRIC CO', range(1, 4), merchant_name='Electric Co')
             + series(10, '25.00', 'ELECTRIC CO', range(4, 7), merchant_name='Electric Co'))
    whole = _build_stream(group, TODAY)
    [bill] = detect([group]).bills
    assert bill['name'] == 'Electric Co' and bill['split_amount'] is None
    assert (bill['cadence'], bill['count'], bill['amount']) == (
        whole['cadence'], whole['count'], whole['amount'])


def _weekly_pair():
    start = date(2026, 4, 6)
    a = [Row(start + timedelta(days=7 * i), '5.00', 'CAFE', merchant_name='Cafe')
         for i in range(10)]
    b = [Row(start + timedelta(days=7 * i + 3), '7.00', 'CAFE', merchant_name='Cafe')
         for i in range(10)]
    return a + b


def _biweekly_pair():
    start = date(2026, 2, 2)
    a = [Row(start + timedelta(days=14 * i), '50.00', 'SITTER', merchant_name='Sitter')
         for i in range(9)]
    b = [Row(start + timedelta(days=14 * i + 3), '60.00', 'SITTER', merchant_name='Sitter')
         for i in range(9)]
    return a + b


def _quarterly_pair():
    a = [Row(d, '80.00', 'PEST CO', merchant_name='Pest Co')
         for d in (date(2025, 6, 1), date(2025, 9, 1), date(2025, 12, 1), date(2026, 3, 1))]
    b = [Row(d, '45.00', 'PEST CO', merchant_name='Pest Co')
         for d in (date(2025, 7, 20), date(2025, 10, 20), date(2026, 1, 20), date(2026, 4, 20))]
    return a + b


def _annual_pair():
    a = [Row(d, '100.00', 'CLUB DUES', merchant_name='Club')
         for d in (date(2024, 7, 1), date(2025, 7, 1))]
    b = [Row(d, '200.00', 'CLUB DUES', merchant_name='Club')
         for d in (date(2024, 11, 15), date(2025, 11, 15))]
    return a + b


def _inactive_monthly_pair():
    return (series(3, '9.00', 'OLD CO BASIC', range(1, 7), year=2025, merchant_name='Old Co')
            + series(25, '14.00', 'OLD CO PLUS', range(1, 7), year=2025, merchant_name='Old Co'))


def test_non_monthly_and_inactive_subsets_are_rejected():
    for make, cadence in [
        (_weekly_pair, 'weekly'), (_biweekly_pair, 'biweekly'),
        (_quarterly_pair, 'quarterly'), (_annual_pair, 'annual'),
        (_inactive_monthly_pair, 'monthly'),
    ]:
        group = make()
        assert _build_stream(group, TODAY) is None, make.__name__
        # Each same-amount subset really is a stream of that cadence on its own…
        amounts = sorted({t.amount for t in group})
        sub = _build_stream([t for t in group if t.amount == amounts[0]], TODAY)
        assert sub is not None and sub['cadence'] == cadence, make.__name__
        # …but none is accepted.
        assert detect([group]).bills == [], make.__name__


def test_inflows_are_never_split():
    group = two_plans(sign='-')
    assert _build_stream(group, TODAY) is None
    found = detect([group])
    assert found.bills == [] and found.income == []


def test_a_subset_with_fewer_than_three_charges_yields_nothing():
    group = (series(3, '9.00', 'EXAMPLE CO BASIC', range(1, 7), merchant_name='Example Co')
             + series(25, '14.00', 'EXAMPLE CO PLUS', (4, 5), merchant_name='Example Co'))
    assert _build_stream(group, TODAY) is None
    assert names(detect([group]).bills) == ['Example Co · $9.00']


def test_a_plan_whose_refunds_broke_detection_is_recovered():
    group = series(3, '9.00', 'EXAMPLE CO BASIC', range(1, 7), merchant_name='Example Co')
    group += [Row(d, '-9.00', 'EXAMPLE CO BASIC', merchant_name='Example Co')
              for d in (date(2026, 2, 5), date(2026, 4, 6), date(2026, 5, 5))]
    assert _build_stream(group, TODAY) is None
    [bill] = detect([group]).bills
    assert (bill['name'], bill['count'], bill['cadence']) == ('Example Co · $9.00', 6, 'monthly')


def test_rows_claimed_by_a_rule_are_never_split():
    found = detect([two_plans()], [rule(pattern='EXAMPLE CO', action='not_recurring')])
    assert found.bills == [] and found.suggestions == []


def test_a_transfer_categorized_subset_is_listed_as_transfer_not_counted():
    bills = detect([two_plans(category='TRANSFER_OUT')]).bills
    assert len(bills) == 2
    assert {b['excluded_reason'] for b in bills} == {'transfer'}
    assert fixed_monthly_total(bills) == (Decimal('0.00'), 0)


def test_a_subset_carries_its_own_flag_fields():
    by_amount = {b['split_amount']: b for b in detect([two_plans()]).bills}
    assert by_amount[Decimal('9.00')]['pattern_hint'] == 'EXAMPLE CO BASIC'
    assert by_amount[Decimal('14.00')]['pattern_hint'] == 'EXAMPLE CO PLUS'
    assert {b['rule_id'] for b in by_amount.values()} == {None}


# --- suggestions -------------------------------------------------------------

def test_an_irregular_merchant_in_four_of_six_months_is_suggested():
    group = visits()
    assert _build_stream(group, TODAY) is None
    found = detect([group])
    assert found.bills == []
    [s] = found.suggestions
    assert (s['name'], s['months'], s['window_months']) == ('Riverside Therapy', 4, 6)
    # Monthly totals 215, 140, 230, 160 → median 187.50.
    assert s['typical_month'] == Decimal('187.50')
    assert s['last_date'] == date(2026, 5, 13)
    assert s['pattern_hint'] == 'RIVERSIDE THERAPY'
    assert (s['is_transfer'], s['has_split']) == (False, False)


def test_three_of_six_months_is_not_suggested():
    assert detect([visits(drop_months=(2,))]).suggestions == []


def test_the_current_month_does_not_count():
    group = visits(drop_months=(2,), extra=[(date(2026, 6, 2), '90.00'),
                                            (date(2026, 6, 10), '90.00')])
    assert detect([group]).suggestions == []


def test_last_charge_may_fall_in_the_current_month():
    [s] = detect([visits(extra=[(date(2026, 6, 9), '90.00')])]).suggestions
    assert s['last_date'] == date(2026, 6, 9) and s['months'] == 4


def test_a_merchant_charged_every_few_days_is_not_suggested():
    start = date(2025, 12, 1)
    amounts = ['11.10', '12.20', '13.30', '14.40', '15.50', '16.60', '17.70']
    group = [Row(start + timedelta(days=3 * i), amounts[i % 7], 'GROCER',
                 merchant_name='Grocer') for i in range(60)]
    found = detect([group])
    assert found.bills == [] and found.suggestions == []


def test_streams_card_payments_and_inflows_are_never_suggested():
    detected = series(10, '95.00', 'ELECTRIC CO', range(1, 7), merchant_name='Electric Co')
    card = visits(name='Card Payment', category='LOAN_PAYMENTS',
                  category_detailed='LOAN_PAYMENTS_CREDIT_CARD_PAYMENT')
    inflow = [Row(t.date, -t.amount, t.description, merchant_name='Refunds Inc')
              for t in visits(name='Refunds Inc')]
    found = detect([detected, card, inflow])
    assert names(found.bills) == ['Electric Co']
    assert found.suggestions == []


def test_a_transfer_group_is_suggested_after_the_others():
    transfer = visits(name='Pay Friend', category='TRANSFER_OUT',
                      extra=[(date(2026, 5, 20), '900.00')])
    found = detect([transfer, visits()])
    assert [(s['name'], s['is_transfer']) for s in found.suggestions] == [
        ('Riverside Therapy', False), ('Pay Friend', True)]


def test_suggestions_sort_by_typical_month_then_name():
    found = detect([visits(name='Alpha Studio'), visits(name='Beta Studio'),
                    visits(name='Gamma Studio', extra=[(date(2026, 5, 27), '500.00')])])
    assert [s['name'] for s in found.suggestions] == [
        'Gamma Studio', 'Alpha Studio', 'Beta Studio']


def test_sub_stream_rows_are_left_out_of_the_groups_suggestion():
    plan = series(3, '9.00', 'RIVERSIDE THERAPY APP', range(1, 7),
                  merchant_name='Riverside Therapy')
    group = plan + visits()
    assert _build_stream(group, TODAY) is None
    found = detect([group])
    assert names(found.bills) == ['Riverside Therapy · $9.00']
    [s] = found.suggestions
    assert s['has_split'] is True
    assert s['typical_month'] == Decimal('187.50')   # the $9.00 plan is not in it
    assert s['last_date'] == date(2026, 5, 13)       # nor its June charge


def test_a_not_recurring_rule_removes_a_suggestion():
    found = detect([visits()], [rule(pattern='RIVERSIDE', action='not_recurring')])
    assert found.suggestions == [] and len(found.marked) == 1


def test_suggestions_never_change_the_headline():
    bill = series(10, '95.00', 'ELECTRIC CO', range(1, 7), merchant_name='Electric Co')
    without = fixed_monthly_total(detect([bill]).bills)
    found = detect([bill, visits()])
    assert found.suggestions and fixed_monthly_total(found.bills) == without


# --- the page ----------------------------------------------------------------

def _seed(app, plans=True, therapy=True):
    with app.app_context():
        inst = Institution(name='Test Bank', slug='test_bank',
                           access_token='tok', item_id='item-1')
        db.session.add(inst)
        db.session.flush()
        db.session.add(Account(institution_id=inst.id, plaid_account_id='acc-1',
                               name='Checking', mask='9999'))
        rows = series(10, '95.00', 'ELECTRIC CO', range(1, 7), merchant_name='Electric Co')
        if plans:
            rows += two_plans()
        if therapy:
            rows += visits()
        for n, t in enumerate(rows):
            db.session.add(Transaction(
                plaid_transaction_id=f's-{n}', institution_id=inst.id,
                account_id='acc-1', date=t.date, description=t.description,
                merchant_name=t.merchant_name, amount=t.amount,
            ))
        db.session.commit()


def _login(client):
    client.post('/login', data={'password': 'testpass'})


@freeze_time(FROZEN)
def test_page_shows_same_amount_streams_with_an_exact_amount_flag(client, app):
    _seed(app, therapy=False)
    _login(client)
    html = client.get('/recurring').get_data(as_text=True)
    assert 'Example Co · $9.00' in html and 'Example Co · $14.00' in html
    assert 'same amount' in html
    assert 'amount_min=9.00' in html and 'amount_max=9.00' in html
    assert 'Possibly recurring' not in html


@freeze_time(FROZEN)
def test_page_lists_possibly_recurring_even_with_nothing_not_counted(client, app):
    _seed(app, plans=False)
    _login(client)
    html = client.get('/recurring').get_data(as_text=True)
    assert 'mb-2">Not counted</h2>' not in html
    assert 'Possibly recurring' in html
    assert 'Riverside Therapy' in html
    assert '4 of last 6 months' in html
    assert '$187.50' in html
    assert 'May 13, 2026' in html
    assert 'pattern=RIVERSIDE+THERAPY' in html
    assert 'action=not_recurring' in html


@freeze_time(FROZEN)
def test_page_without_either_renders_as_before(client, app):
    _seed(app, plans=False, therapy=False)
    _login(client)
    res = client.get('/recurring')
    html = res.get_data(as_text=True)
    assert res.status_code == 200
    assert 'Electric Co' in html
    assert 'same amount' not in html and 'Possibly recurring' not in html


@freeze_time(FROZEN)
def test_suggestion_links_are_a_flag_and_a_not_recurring(client, app):
    _seed(app, plans=False)
    _login(client)
    html = client.get('/recurring').get_data(as_text=True)
    links = re.findall(r'href="([^"]*pattern=RIVERSIDE\+THERAPY[^"]*)"', html)
    assert len(links) == 2
    assert sum('action=not_recurring' in link for link in links) == 1


@freeze_time(FROZEN)
def test_suggestion_beside_a_same_amount_stream_has_only_the_note(client, app):
    _seed(app, plans=False, therapy=False)
    with app.app_context():
        inst_id = Institution.query.one().id
        for n, t in enumerate(series(3, '9.00', 'RIVERSIDE THERAPY APP', range(1, 7),
                                     merchant_name='Riverside Therapy') + visits()):
            db.session.add(Transaction(
                plaid_transaction_id=f'p-{n}', institution_id=inst_id,
                account_id='acc-1', date=t.date, description=t.description,
                merchant_name=t.merchant_name, amount=t.amount,
            ))
        db.session.commit()
    _login(client)
    html = client.get('/recurring').get_data(as_text=True)
    assert 'Riverside Therapy · $9.00' in html
    assert 'Flag its same-amount stream first' in html
    assert 'action=not_recurring' not in html
    # Only the sub-stream's own Flag link, with its exact amount, remains.
    links = re.findall(r'href="([^"]*pattern=RIVERSIDE\+THERAPY[^"]*)"', html)
    assert len(links) == 1 and 'amount_min=9.00' in links[0]
