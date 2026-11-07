"""Essential marks on /recurring (app/bills.py keys and totals, app/routes.py).

All fixtures are fictional. Pure functions use fixed dates (knowledge 004);
route tests freeze the clock and log in inside the frozen block, because
Flask's session cookie is timestamped.
"""

from datetime import date
from decimal import Decimal
import re

from flask import get_template_attribute
from freezegun import freeze_time

from app.bills import (
    detect_recurring_with_rules, essential_monthly_total, fixed_monthly_total,
    mark_essential,
)
from app.models import Account, EssentialMark, Institution, RecurringRule, Transaction, db
from app.subscriptions import grouping_key
from tests.test_same_amount_streams import Row, rule, series, two_plans

TODAY = date(2026, 6, 13)
FROZEN = '2026-06-13'


def detect(groups, rules=()):
    return detect_recurring_with_rules(groups, TODAY, list(rules))


def by_name(streams):
    return {s['name']: s for s in streams}


def renamed():
    """One monthly bill whose merchant name Plaid changed in April; the card
    descriptor stayed the same, so merge_by_descriptor joins the two groups."""
    old = series(5, '20.00', 'BRIGHTLINE*MEDIA', range(1, 4), merchant_name='Brightline')
    new = series(5, '20.00', 'BRIGHTLINE*MEDIA', range(4, 7), merchant_name='Brightline Media')
    return old, new


# --- keys ----------------------------------------------------------------------

def test_whole_group_stream_is_keyed_by_its_grouping_key():
    rows = series(10, '95.00', 'Electric Co', range(1, 7), merchant_name='Electric Co')
    [bill] = detect([rows]).bills
    assert bill['essential_keys'] == ('merchant:electric co',)
    assert bill['essential_key'] == 'merchant:electric co'
    assert bill['essential'] is False


def test_merged_group_carries_both_names_keys():
    old, new = renamed()
    [bill] = detect([old, new]).bills
    assert bill['essential_keys'] == ('merchant:brightline', 'merchant:brightline media')
    # Three rows each: the tie goes to the smaller key.
    assert bill['essential_key'] == 'merchant:brightline'
    # A mark made under either name still matches after the merge.
    for key in bill['essential_keys']:
        assert mark_essential(detect([old, new]).bills, {key})[0]['essential'] is True


def test_same_amount_sub_streams_are_keyed_by_amount_and_marked_alone():
    bills = by_name(detect([two_plans()]).bills)
    basic, plus = bills['Example Co · $9.00'], bills['Example Co · $14.00']
    assert basic['essential_keys'] == ('merchant:example co@9.00',)
    assert plus['essential_keys'] == ('merchant:example co@14.00',)
    # Marking one plan never marks the other, and the parent key matches neither.
    mark_essential([basic, plus], {'merchant:example co@9.00'})
    assert (basic['essential'], plus['essential']) == (True, False)
    mark_essential([basic, plus], {'merchant:example co'})
    assert (basic['essential'], plus['essential']) == (False, False)


def test_sub_stream_of_a_merged_group_has_an_amount_key_per_grouping_key():
    rows = two_plans()
    for r in rows:
        if r.date.month >= 4:
            r.merchant_name = 'Example Company'
    old = [r for r in rows if r.date.month < 4]
    new = [r for r in rows if r.date.month >= 4]
    bills = by_name(detect([old, new]).bills)
    [basic] = [b for name, b in bills.items() if name.endswith('$9.00')]
    assert basic['essential_keys'] == (
        'merchant:example co@9.00', 'merchant:example company@9.00',
    )


def test_rule_stream_is_keyed_by_rule_id_and_income_has_no_keys():
    bill_rows = series(1, '310.00', 'Check #1001', range(1, 7))
    pay = series(15, '-2000.00', 'ACME PAYROLL', range(1, 7), merchant_name='Acme',
                 category='INCOME_WAGES')
    found = detect([bill_rows, pay], [rule(id=7, label='Landlord', pattern='Check')])
    [bill] = found.bills
    assert (bill['name'], bill['essential_keys'], bill['essential_key']) == (
        'Landlord', ('rule:7',), 'rule:7')
    [income] = found.income
    assert (income['essential_keys'], income['essential_key']) == ((), None)


def test_keys_too_long_to_store_are_left_out():
    from app.bills import ESSENTIAL_KEY_MAX_LENGTH, _merchant_keys
    fits = Row(TODAY, '5.00', 'x')
    fits.merchant_entity_id = 'e' * (ESSENTIAL_KEY_MAX_LENGTH - len('merchant:entity:'))
    too_long = Row(TODAY, '5.00', 'x')
    too_long.merchant_entity_id = fits.merchant_entity_id + 'e'
    [key], _ = _merchant_keys([fits])
    assert len(key) == ESSENTIAL_KEY_MAX_LENGTH
    assert _merchant_keys([too_long]) == ((), None)
    # The amount suffix counts toward the limit too.
    assert _merchant_keys([fits], suffix='@9.00') == ((), None)


def test_rows_without_a_grouping_key_get_no_keys():
    # Detection never groups such rows; the helper still answers safely.
    from app.bills import _merchant_keys
    rows = [Row(TODAY, '5.00', '1234')]
    assert grouping_key(rows[0]) == ''
    assert _merchant_keys(rows) == ((), None)


# --- totals --------------------------------------------------------------------

def _bills():
    found = detect([
        series(10, '95.00', 'Electric Co', range(1, 7), merchant_name='Electric Co'),
        series(5, '15.99', 'Streamflix', range(1, 7), merchant_name='Streamflix'),
        # Annual: listed but not counted.
        [Row(date(2025, 3, 1), '120.00', 'Domain Host', merchant_name='Domain Host'),
         Row(date(2026, 3, 1), '120.00', 'Domain Host', merchant_name='Domain Host')],
    ])
    return found.bills


def test_essential_total_sums_only_counted_essential_bills():
    bills = mark_essential(_bills(), {'merchant:electric co', 'merchant:domain host'})
    names = {b['name']: b for b in bills}
    assert names['Domain Host']['excluded_reason'] is not None   # marked, not counted
    total, count = fixed_monthly_total(bills)
    essential, essential_count = essential_monthly_total(bills)
    assert (essential, essential_count) == (names['Electric Co']['monthly_amount'], 1)
    assert count == 2 and total - essential == names['Streamflix']['monthly_amount']


def test_no_marks_means_no_essential_total():
    bills = mark_essential(_bills(), set())
    assert essential_monthly_total(bills) == (Decimal('0.00'), 0)


# --- routes --------------------------------------------------------------------

def _seed(app, with_plans=False, rules=()):
    with app.app_context():
        inst = Institution(name='Test Bank', slug='test_bank',
                           access_token='tok', item_id='item-1')
        db.session.add(inst)
        db.session.flush()
        db.session.add(Account(institution_id=inst.id, plaid_account_id='acc-1',
                               name='Checking', mask='9999'))
        rows = (
            series(10, '95.00', 'Electric Co', range(1, 7), merchant_name='Electric Co')
            + series(5, '15.99', 'Streamflix', range(1, 7), merchant_name='Streamflix')
            + sum(renamed(), [])
            + series(1, '310.00', 'Check #1001', range(1, 7))
        )
        if with_plans:
            rows += two_plans()
        for n, r in enumerate(rows):
            db.session.add(Transaction(
                plaid_transaction_id=f'e-{n}', institution_id=inst.id,
                account_id='acc-1', date=r.date, description=r.description,
                merchant_name=r.merchant_name, amount=r.amount,
            ))
        for values in rules:
            db.session.add(RecurringRule(**values))
        db.session.commit()


def _login(client):
    client.post('/login', data={'password': 'testpass'})


def _mark(client, essential, *keys):
    return client.post('/recurring/essential',
                       data={'essential': essential, 'key': list(keys)})


def _saved(app):
    with app.app_context():
        return sorted(m.stream_key for m in EssentialMark.query.all())


def _money(text):
    return Decimal(text.replace(',', ''))


def _split(html):
    """(total, essential, not essential, "N of M") from the headline card."""
    total = re.search(r'amount-xl">\$([\d,.]+) / month', html).group(1)
    block = html.split('id="essential-split"', 1)[1].split('</div>\n    </div>', 1)[0]
    essential = re.search(r'Essential \$([\d,.]+) / month', block).group(1)
    rest = re.search(r'Not essential \$([\d,.]+) / month', block).group(1)
    of = re.search(r'(\d+ of \d+)', block).group(1)
    return _money(total), _money(essential), _money(rest), of


def _row(html, name):
    counted = html.split('id="counted"', 1)[1].split('</table>', 1)[0]
    return next(tr for tr in counted.split('<tr>') if name in tr)


@freeze_time(FROZEN)
def test_mark_and_unmark_updates_the_row_and_the_header(client, app):
    _seed(app)
    _login(client)
    html = client.get('/recurring').get_data(as_text=True)
    total, essential, rest, of = _split(html)
    assert essential == Decimal('0.00') and rest == total and of == '0 of 4'
    assert 'Mark essential' in _row(html, 'Electric Co')

    res = _mark(client, '1', 'merchant:electric co')
    assert res.status_code == 302 and res.headers['Location'].endswith('/recurring#counted')
    assert _saved(app) == ['merchant:electric co']
    html = client.get('/recurring').get_data(as_text=True)
    assert 'aria-pressed="true"' in _row(html, 'Electric Co')
    assert 'aria-pressed="false"' in _row(html, 'Streamflix')
    total2, essential, rest, of = _split(html)
    assert total2 == total and essential == Decimal('95.00') and of == '1 of 4'
    assert essential + rest == total

    _mark(client, '0', 'merchant:electric co')
    assert _saved(app) == []
    _, essential, rest, _ = _split(client.get('/recurring').get_data(as_text=True))
    assert essential == Decimal('0.00') and rest == total


@freeze_time(FROZEN)
def test_merged_stream_off_form_clears_every_key(client, app):
    _seed(app)
    _login(client)
    # Marked under each name: the off form posts both keys and clears both.
    _mark(client, '1', 'merchant:brightline')
    _mark(client, '1', 'merchant:brightline media')
    html = client.get('/recurring').get_data(as_text=True)
    row = _row(html, 'Brightline')
    assert 'aria-pressed="true"' in row
    keys = re.findall(r'name="key" value="([^"]+)"', row)
    assert keys == ['merchant:brightline', 'merchant:brightline media']
    _mark(client, '0', *keys)
    assert _saved(app) == []
    assert 'aria-pressed="false"' in _row(client.get('/recurring').get_data(as_text=True),
                                          'Brightline')


@freeze_time(FROZEN)
def test_marking_one_same_amount_plan_marks_only_that_row(client, app):
    _seed(app, with_plans=True)
    _login(client)
    _mark(client, '1', 'merchant:example co@9.00')
    html = client.get('/recurring').get_data(as_text=True)
    assert 'aria-pressed="true"' in _row(html, 'Example Co · $9.00')
    assert 'aria-pressed="false"' in _row(html, 'Example Co · $14.00')


@freeze_time(FROZEN)
def test_rule_stream_toggles_and_its_mark_goes_with_the_rule(client, app):
    _seed(app, rules=[dict(label='Landlord', pattern='Check', direction='outflow',
                           action='recurring')])
    _login(client)
    with app.app_context():
        rule_id = RecurringRule.query.one().id
    _mark(client, '1', f'rule:{rule_id}')
    html = client.get('/recurring').get_data(as_text=True)
    assert 'aria-pressed="true"' in _row(html, 'Landlord')
    _mark(client, '0', f'rule:{rule_id}')
    assert _saved(app) == []
    _mark(client, '1', f'rule:{rule_id}')
    client.post(f'/recurring/rules/{rule_id}/delete')
    assert _saved(app) == []


@freeze_time(FROZEN)
def test_marking_twice_saves_one_mark(client, app):
    _seed(app)
    _login(client)
    _mark(client, '1', 'merchant:streamflix')
    _mark(client, '1', 'merchant:streamflix')
    assert _saved(app) == ['merchant:streamflix']


@freeze_time(FROZEN)
def test_mark_saved_concurrently_is_already_essential(client, app, monkeypatch):
    # The pre-check misses a mark another request saved in between: the
    # unique constraint rejects the insert, and the request still succeeds.
    import app.routes as routes
    _seed(app)
    _login(client)
    _mark(client, '1', 'merchant:streamflix')
    monkeypatch.setattr(routes, '_essential_keys', lambda: set())
    res = _mark(client, '1', 'merchant:streamflix')
    assert res.status_code == 302
    assert _saved(app) == ['merchant:streamflix']
    monkeypatch.undo()
    assert 'aria-pressed="true"' in _row(client.get('/recurring').get_data(as_text=True),
                                         'Streamflix')


@freeze_time(FROZEN)
def test_bad_toggle_requests_are_rejected(client, app):
    _login(client)
    assert _mark(client, '1').status_code == 400                         # no key
    assert _mark(client, '1', 'electric co').status_code == 400          # no prefix
    assert _mark(client, '2', 'merchant:x').status_code == 400           # bad flag
    assert _mark(client, '1', 'merchant:' + 'x' * 247).status_code == 400   # 256 chars
    assert _mark(client, '1', 'merchant:' + 'x' * 246).status_code == 302   # 255 chars
    assert _mark(client, '0', *[f'merchant:{i}' for i in range(501)]).status_code == 400
    assert _mark(client, '0', *[f'merchant:{i}' for i in range(500)]).status_code == 302
    # Marking takes exactly one key: the page only ever posts the primary one.
    assert _mark(client, '1', 'merchant:a', 'merchant:b').status_code == 400


def test_toggle_requires_login(client, app):
    res = _mark(client, '1', 'merchant:electric co')
    assert res.status_code == 302 and '/login' in res.headers['Location']
    assert _saved(app) == []


def test_bill_without_keys_renders_no_toggle(app):
    with app.test_request_context():
        toggle = get_template_attribute('_essential_toggle.html', 'essential_toggle')
        assert '<form' not in toggle({'essential_keys': (), 'essential_key': None,
                                      'essential': False})
        assert '<form' in toggle({'essential_keys': ('merchant:x',),
                                  'essential_key': 'merchant:x', 'essential': False})


def test_page_query_count_does_not_grow_with_marks(app):
    """Marks are one plain column read, whatever their number."""
    from tests.test_merchant_groups import _count_selects, _seed_page_corpus
    counts = []
    for n_marks in (1, 10):
        with app.app_context():
            db.drop_all()
            db.create_all()
            _seed_page_corpus(5)
            for i in range(n_marks):
                db.session.add(EssentialMark(stream_key=f'merchant:zz{i}zz'))
            db.session.commit()
            client = app.test_client()
            client.post('/login', data={'password': 'testpass'})
            db.session.expunge_all()
            response, selects = _count_selects(lambda: client.get('/recurring'))
            assert response.status_code == 200
            counts.append(selects)
    assert counts[0] == counts[1], counts
