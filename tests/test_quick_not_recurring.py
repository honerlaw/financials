"""One-click "Not recurring" on /recurring (routes.quick_not_recurring_rule).

All fixtures are fictional. Pure functions use fixed dates (knowledge 004);
route tests freeze the clock and log in inside the frozen block, because
Flask's session cookie is timestamped.
"""

from datetime import date
from decimal import Decimal
import re

import pytest
from freezegun import freeze_time

from app.bills import detect_recurring_with_rules
from app.models import Account, EssentialMark, Institution, RecurringRule, Transaction, db
from app.recurring_rules import locate_stream, preview, quick_mark_verdict
from tests.test_recurring_rules import Row, monthly, rule

TODAY = date(2026, 6, 13)
FROZEN = '2026-06-13'


# ── quick_mark_verdict ───────────────────────────────────────────────────────

def _verdict(groups, saved=(), pick=lambda found: found.bills[0], direction='outflow'):
    saved = list(saved)
    found = detect_recurring_with_rules(groups, TODAY, saved)
    stream = pick(found)
    split = stream.get('split_amount')
    candidate = rule(id=None, label=stream['name'], pattern=stream['pattern_hint'],
                     direction=direction, action='not_recurring',
                     amount_min=split, amount_max=split)
    result = preview(groups, saved, candidate)
    assert locate_stream(found, stream['stream_keys'], split, direction) is stream
    return quick_mark_verdict(stream, result, direction), result


def test_preview_returns_the_rows_the_candidate_would_win():
    groups = [monthly('NORTHWIND STREAMING', '15.99', merchant_name='Northwind')]
    result = preview(groups, [], rule(id=None, pattern='NORTHWIND', action='not_recurring'))
    assert result['won'] == 5
    assert [id(r) for r in result['won_rows']] == [id(r) for r in groups[0]]


def test_a_hint_claiming_exactly_the_stream_saves():
    groups = [monthly('NORTHWIND STREAMING', '15.99', merchant_name='Northwind')]
    verdict, _ = _verdict(groups)
    assert verdict is True


def test_a_hint_that_also_claims_another_groups_rows_goes_to_the_form():
    groups = [
        monthly('NORTHWIND STREAMING', '15.99', merchant_name='Northwind'),
        monthly('NORTHWIND STREAMING KIDS', '7.99', day=20, merchant_name='Tailspin Toys'),
    ]
    verdict, result = _verdict(groups, pick=lambda f: next(
        b for b in f.bills if b['name'] == 'Northwind'))
    assert result['won'] == 10
    assert verdict is False


def test_a_hint_covering_only_part_of_the_stream_goes_to_the_form():
    # No common prefix of 3+ characters, so the hint falls back to the most
    # common description and matches only 3 of the stream's 5 rows.
    descriptions = ['GYMCO DUES', 'FIT MEMBERSHIP', 'GYMCO DUES', 'FIT MEMBERSHIP', 'GYMCO DUES']
    group = [Row(date(2026, m, 8), '40.00', d, merchant_name='Gym Co')
             for m, d in zip(range(1, 6), descriptions)]
    verdict, result = _verdict([group])
    assert result['won'] == 3
    assert verdict is False


def test_taken_rows_alone_refuse_a_save():
    """Rows taken from a saved rule refuse a save even if the sets matched."""
    groups = [monthly('NORTHWIND STREAMING', '15.99', merchant_name='Northwind')]
    found = detect_recurring_with_rules(groups, TODAY, [])
    stream = found.bills[0]
    result = {'won_rows': list(stream['rows']), 'taken': [{'label': 'x', 'pattern': 'y', 'rows': 1}]}
    assert quick_mark_verdict(stream, result, 'outflow') is False
    assert quick_mark_verdict(stream, {**result, 'taken': []}, 'outflow') is True


def test_locate_stream_needs_keys_side_and_amount_to_match():
    groups = [monthly('NORTHWIND STREAMING', '15.99', merchant_name='Northwind')]
    found = detect_recurring_with_rules(groups, TODAY, [])
    [bill] = found.bills
    assert locate_stream(found, ['northwind'], None, 'outflow') is bill
    assert locate_stream(found, ['no such key'], None, 'outflow') is None
    assert locate_stream(found, ['northwind'], None, 'inflow') is None
    assert locate_stream(found, ['northwind'], Decimal('15.99'), 'outflow') is None


# ── detection carries rows and stream keys ──────────────────────────────────

def test_streams_and_suggestions_carry_their_rows_and_keys():
    bill = monthly('NORTHWIND STREAMING', '15.99', merchant_name='Northwind')
    pay = monthly('CONTOSO PAYROLL', '-2000.00', day=1, merchant_name='Contoso',
                  category='INCOME')
    plans = (monthly('EXAMPLE CO BASIC', '9.00', n=6, day=3, merchant_name='Example Co')
             + monthly('EXAMPLE CO PLUS', '14.00', n=5, day=25, merchant_name='Example Co'))
    visits = [Row(date(2026, m, d), a, 'RIVERSIDE THERAPY', merchant_name='Riverside')
              for m, d, a in ((1, 7, '120'), (1, 21, '95'), (2, 11, '140'), (3, 4, '120'),
                              (3, 25, '110'), (5, 13, '160'))]
    ruled = monthly('FABRIKAM GYM', '30.00', merchant_name='Fabrikam')
    found = detect_recurring_with_rules(
        [bill, pay, plans, visits, ruled], TODAY, [rule(id=7, pattern='FABRIKAM')])
    by_name = {s['name']: s for s in found.bills + found.income}
    assert by_name['Northwind']['stream_keys'] == ('northwind',)
    assert [id(r) for r in by_name['Northwind']['rows']] == [id(r) for r in bill]
    assert by_name['Contoso']['stream_keys'] == ('contoso',)
    basic = by_name['Example Co · $9.00']
    assert basic['stream_keys'] == ('example co',) and len(basic['rows']) == 6
    assert by_name['My rule']['stream_keys'] == ()
    [suggestion] = found.suggestions
    assert suggestion['stream_keys'] == ('riverside',) and len(suggestion['rows']) == 6


# ── the route ────────────────────────────────────────────────────────────────

def _seed(app, rows):
    """`rows`: (date, amount, description, extra Transaction columns)."""
    with app.app_context():
        inst = Institution(name='Test Bank', slug='test_bank',
                           access_token='tok', item_id='item-1')
        db.session.add(inst)
        db.session.flush()
        db.session.add(Account(institution_id=inst.id, plaid_account_id='acc-1',
                               name='Checking', mask='9999'))
        for n, (d, amount, description, extra) in enumerate(rows):
            db.session.add(Transaction(
                plaid_transaction_id=f'q-{n}', institution_id=inst.id,
                account_id='acc-1', date=d, description=description,
                amount=Decimal(amount), **extra,
            ))
        db.session.commit()


def _monthly(description, amount, day=10, months=range(1, 7), **extra):
    return [(date(2026, m, day), amount, description, extra) for m in months]


def _base():
    return (_monthly('NORTHWIND STREAMING', '15.99', merchant_name='Northwind')
            + _monthly('ELECTRIC CO', '95.00', day=4, merchant_name='Electric Co')
            + _monthly('CONTOSO PAYROLL', '-2000.00', day=1, merchant_name='Contoso',
                       category='INCOME'))


def _login(client):
    client.post('/login', data={'password': 'testpass'})


def _quick_form(html, name):
    """The quick "Not recurring" form fields on the row named `name`."""
    for chunk in html.split('<tr'):
        if (re.search(r'<td class="medium">\s*' + re.escape(name) + r'\s*<', chunk)
                and 'rules/quick' in chunk):
            form = chunk.split('action="/recurring/rules/quick"', 1)[1].split('</form>', 1)[0]
            data = {}
            for field, value in re.findall(r'name="([^"]+)" value="([^"]*)"', form):
                data.setdefault(field, []).append(value)
            return data
    raise AssertionError(f'no quick form for {name}')


def _rules(app):
    with app.app_context():
        return [(r.label, r.pattern, r.direction, r.action, r.amount_min, r.amount_max)
                for r in RecurringRule.query.order_by(RecurringRule.id)]


def _counted(html):
    return html.split('id="counted"', 1)[1].split('</table>', 1)[0]


@freeze_time(FROZEN)
def test_quick_marking_a_bill_saves_a_rule_and_confirms_it(client, app):
    _seed(app, _base())
    _login(client)
    html = client.get('/recurring').get_data(as_text=True)
    assert 'Northwind' in _counted(html)
    res = client.post('/recurring/rules/quick', data=_quick_form(html, 'Northwind'))
    assert res.status_code == 302
    assert res.headers['Location'].endswith('/recurring?marked=1#marked-notice')
    assert _rules(app) == [('Northwind', 'NORTHWIND STREAMING', 'outflow',
                            'not_recurring', None, None)]
    page = client.get('/recurring?marked=1').get_data(as_text=True)
    assert 'Northwind' not in _counted(page)
    notice = page.split('id="marked-notice"', 1)[1].split('</div>\n</div>', 1)[0]
    assert 'Marked <span class="strong">Northwind</span> not recurring' in notice
    assert 'matching "NORTHWIND STREAMING"' in notice
    assert 'action="/recurring/rules/1/delete"' in notice
    marked = page.split('Marked not recurring (1)', 1)[1].split('</table>', 1)[0]
    assert 'Northwind' in marked and 'action="/recurring/rules/1/delete"' in marked
    assert '<details class="disclosure" open>' in page


@freeze_time(FROZEN)
def test_quick_marking_income_saves_an_inflow_rule(client, app):
    _seed(app, _base())
    _login(client)
    html = client.get('/recurring').get_data(as_text=True)
    res = client.post('/recurring/rules/quick', data=_quick_form(html, 'Contoso'))
    assert res.status_code == 302 and 'marked=1' in res.headers['Location']
    assert _rules(app) == [('Contoso', 'CONTOSO PAYROLL', 'inflow', 'not_recurring', None, None)]


@freeze_time(FROZEN)
@pytest.mark.parametrize('basic', ['9.00', '12.34'])
def test_quick_marking_a_same_amount_plan_ranges_it_to_that_amount(client, app, basic):
    _seed(app, _monthly('EXAMPLE CO BASIC', basic, day=3, merchant_name='Example Co')
          + _monthly('EXAMPLE CO PLUS', '14.00', day=25, months=range(1, 6),
                     merchant_name='Example Co'))
    _login(client)
    html = client.get('/recurring').get_data(as_text=True)
    form = _quick_form(html, f'Example Co · ${basic}')
    assert form['split_amount'] == [basic]
    res = client.post('/recurring/rules/quick', data=form)
    assert 'marked=1' in res.headers['Location']
    [(_label, pattern, _dir, _action, low, high)] = _rules(app)
    assert pattern == 'EXAMPLE CO BASIC' and low == high == Decimal(basic)
    # The other plan's rows are now the whole group, so it is the merchant's
    # own stream (no amount suffix), still counted at its own price.
    counted = _counted(client.get('/recurring').get_data(as_text=True))
    assert f'Example Co · ${basic}' not in counted
    assert re.search(r'Example Co\s*<', counted) and '-$14.00' in counted
    assert f'-${basic}' not in counted


@freeze_time(FROZEN)
def test_quick_marking_a_merged_stream_claims_both_groups(client, app):
    # Plaid renamed the merchant mid-history; the card descriptor stayed, so
    # the two index groups merge into one stream with two keys.
    rows = [(date(2026, m, 12), '250.00', 'PAYCO* CONTOSO SERVICES',
             {'merchant_name': 'Fabrikam Inc' if m >= 5 else 'Contoso Ltd',
              'merchant_entity_id': 'ent-fabrikam' if m >= 5 else None})
            for m in range(1, 7)]
    _seed(app, rows)
    _login(client)
    html = client.get('/recurring').get_data(as_text=True)
    form = _quick_form(html, 'Contoso Ltd')
    assert len(form['stream_key']) == 2
    res = client.post('/recurring/rules/quick', data=form)
    assert 'marked=1' in res.headers['Location']
    page = client.get('/recurring').get_data(as_text=True)
    marked = page.split('Marked not recurring (1)', 1)[1].split('</table>', 1)[0]
    assert re.search(r'<td class="right">6</td>', marked)


@freeze_time(FROZEN)
def test_a_hint_reaching_another_group_opens_the_previewing_form(client, app):
    _seed(app, _base() + _monthly('NORTHWIND STREAMING KIDS', '7.99', day=20,
                                  merchant_name='Tailspin Toys'))
    _login(client)
    html = client.get('/recurring').get_data(as_text=True)
    res = client.post('/recurring/rules/quick', data=_quick_form(html, 'Northwind'))
    assert _rules(app) == []
    location = res.headers['Location']
    assert '/recurring/rules/new?' in location
    assert 'action=not_recurring' in location and 'preview=1' in location
    form = client.get(location).get_data(as_text=True)
    assert 'This rule would claim 12 transactions' in form
    assert re.search(r'value="not_recurring"\s+checked', form)


@freeze_time(FROZEN)
def test_a_hint_covering_part_of_the_stream_opens_the_form(client, app):
    descriptions = ['GYMCO DUES', 'FIT MEMBERSHIP'] * 3
    _seed(app, [(date(2026, m, 8), '40.00', d, {'merchant_name': 'Gym Co'})
                for m, d in zip(range(1, 7), descriptions)])
    _login(client)
    html = client.get('/recurring').get_data(as_text=True)
    res = client.post('/recurring/rules/quick', data=_quick_form(html, 'Gym Co'))
    assert _rules(app) == []
    assert 'preview=1' in res.headers['Location']


@freeze_time(FROZEN)
def test_a_hint_too_short_to_save_opens_the_form(client, app):
    _seed(app, _monthly('AB', '25.00', merchant_name='Ab Co'))
    _login(client)
    html = client.get('/recurring').get_data(as_text=True)
    res = client.post('/recurring/rules/quick', data=_quick_form(html, 'Ab Co'))
    assert _rules(app) == []
    assert 'preview=1' in res.headers['Location'] and 'pattern=AB' in res.headers['Location']


@freeze_time(FROZEN)
def test_reposting_a_marked_plan_confirms_its_own_rule(client, app):
    _seed(app, _monthly('EXAMPLE CO BASIC', '9.00', day=3, merchant_name='Example Co')
          + _monthly('EXAMPLE CO PLUS', '14.00', day=25, months=range(1, 6),
                     merchant_name='Example Co'))
    _login(client)
    html = client.get('/recurring').get_data(as_text=True)
    plan = _quick_form(html, 'Example Co · $9.00')
    first = client.post('/recurring/rules/quick', data=plan)
    # Reposted from the stale page, with the amount written differently.
    again = client.post('/recurring/rules/quick', data={**plan, 'split_amount': '9.0'})
    assert len(_rules(app)) == 1
    assert again.headers['Location'] == first.headers['Location']
    # The same keys without an amount now locate the other plan, which became
    # the merchant's whole-group stream: a rule of its own, not the plan's.
    rest = client.post('/recurring/rules/quick',
                       data={'stream_key': plan['stream_key'], 'direction': 'outflow'})
    assert 'marked=2' in rest.headers['Location']
    assert [(r[1], r[4]) for r in _rules(app)] == [('EXAMPLE CO BASIC', Decimal('9.00')),
                                                   ('EXAMPLE CO PLUS', None)]


@freeze_time(FROZEN)
def test_posting_the_same_quick_mark_twice_saves_one_rule(client, app):
    _seed(app, _base())
    _login(client)
    form = _quick_form(client.get('/recurring').get_data(as_text=True), 'Northwind')
    first = client.post('/recurring/rules/quick', data=form)
    second = client.post('/recurring/rules/quick', data=form)
    assert len(_rules(app)) == 1
    assert second.headers['Location'] == first.headers['Location']


@freeze_time(FROZEN)
@pytest.mark.parametrize('data', [
    {},
    {'direction': 'outflow'},
    {'direction': 'sideways', 'stream_key': ['northwind']},
    {'direction': 'outflow', 'stream_key': [f'k{i}' for i in range(501)]},
    {'direction': 'outflow', 'stream_key': ['no such merchant']},
    {'direction': 'outflow', 'stream_key': ['northwind'], 'split_amount': 'abc'},
    {'direction': 'outflow', 'stream_key': ['northwind'], 'split_amount': 'NaN'},
    {'direction': 'outflow', 'stream_key': ['northwind'], 'split_amount': 'Infinity'},
])
def test_malformed_or_unknown_posts_save_nothing(client, app, data):
    _seed(app, _base())
    _login(client)
    res = client.post('/recurring/rules/quick', data=data)
    assert res.status_code == 302 and res.headers['Location'].endswith('/recurring')
    assert _rules(app) == []


def test_quick_route_requires_login(client, app):
    res = client.post('/recurring/rules/quick', data={'stream_key': 'x', 'direction': 'outflow'})
    assert res.status_code == 302 and '/login' in res.headers['Location']
    assert _rules(app) == []


@freeze_time(FROZEN)
def test_every_flagged_row_has_a_button_and_rule_rows_do_not(client, app):
    _seed(app, _base() + _monthly('FABRIKAM GYM', '30.00', day=15, merchant_name='Fabrikam'))
    with app.app_context():
        db.session.add(RecurringRule(label='Gym', pattern='FABRIKAM', direction='outflow',
                                     action='recurring'))
        db.session.commit()
    _login(client)
    html = client.get('/recurring').get_data(as_text=True)
    flags = html.count('>Flag</a>')
    assert flags == 3
    assert html.count('action="/recurring/rules/quick"') == flags
    gym_row = next(c for c in _counted(html).split('<tr') if 'Gym' in c)
    assert 'rules/quick' not in gym_row


@freeze_time(FROZEN)
def test_undo_on_the_marked_row_counts_the_bill_again(client, app):
    _seed(app, _base())
    _login(client)
    html = client.get('/recurring').get_data(as_text=True)
    client.post('/recurring/rules/quick', data=_quick_form(html, 'Northwind'))
    res = client.post('/recurring/rules/1/delete')
    assert res.status_code == 302 and _rules(app) == []
    assert 'Northwind' in _counted(client.get('/recurring').get_data(as_text=True))


@freeze_time(FROZEN)
def test_an_essential_mark_survives_a_quick_mark_and_undo(client, app):
    _seed(app, _base())
    _login(client)
    client.post('/recurring/essential', data={'essential': '1', 'key': 'merchant:northwind'})
    html = client.get('/recurring').get_data(as_text=True)
    client.post('/recurring/rules/quick', data=_quick_form(html, 'Northwind'))
    client.post('/recurring/rules/1/delete')
    with app.app_context():
        assert [m.stream_key for m in EssentialMark.query.all()] == ['merchant:northwind']
    row = next(c for c in _counted(client.get('/recurring').get_data(as_text=True)).split('<tr')
               if 'Northwind' in c)
    assert 'aria-pressed="true"' in row


@freeze_time(FROZEN)
@pytest.mark.parametrize('marked', ['999', 'abc', ''])
def test_an_unknown_or_malformed_marked_id_shows_no_notice(client, app, marked):
    _seed(app, _base())
    with app.app_context():
        db.session.add(RecurringRule(label='Not this', pattern='ELECTRIC', direction='outflow',
                                     action='recurring'))
        db.session.commit()
    _login(client)
    res = client.get(f'/recurring?marked={marked}')
    assert res.status_code == 200
    assert 'id="marked-notice"' not in res.get_data(as_text=True)
    # A recurring rule's id is no "marked not recurring" notice either.
    assert 'id="marked-notice"' not in client.get('/recurring?marked=1').get_data(as_text=True)
