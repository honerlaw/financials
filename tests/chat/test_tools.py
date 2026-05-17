from datetime import date

from freezegun import freeze_time

from app.chat import tools


def test_current_date_returns_today():
    result = tools.current_date()
    assert result == {'date': date.today().isoformat()}


def test_get_date_range_empty_db(app):
    with app.app_context():
        result = tools.get_date_range()
    assert result == {'earliest': None, 'latest': None}


def test_get_date_range_with_seed(app, seed_data):
    with app.app_context():
        result = tools.get_date_range()
    assert result == {'earliest': '2026-01-05', 'latest': '2026-03-15'}


def test_dispatch_unknown_tool():
    result = tools.dispatch('nonexistent', {})
    assert 'error' in result


def test_openai_schemas_includes_current_date():
    schemas = tools.openai_schemas()
    names = [s['function']['name'] for s in schemas]
    assert 'current_date' in names
    assert 'get_date_range' in names


def test_list_institutions(app, seed_data):
    with app.app_context():
        result = tools.dispatch('list_institutions', {})
    names = {i['name'] for i in result['institutions']}
    assert names == {'Truist', 'Amex'}
    for i in result['institutions']:
        assert {'id', 'name', 'slug', 'status'} <= set(i.keys())


def test_query_transactions_date_range(app, seed_data):
    with app.app_context():
        result = tools.dispatch('query_transactions', {
            'start_date': '2026-02-01', 'end_date': '2026-02-28',
        })
    assert result['count'] == 3
    assert result['truncated'] is False
    dates = sorted(r['date'] for r in result['rows'])
    assert dates == ['2026-02-05', '2026-02-14', '2026-02-22']


def test_query_transactions_merchant_filter(app, seed_data):
    with app.app_context():
        result = tools.dispatch('query_transactions', {
            'start_date': '2026-01-01', 'end_date': '2026-12-31',
            'merchant_contains': 'whole',
        })
    assert result['count'] == 3
    assert all('whole' in r['description'].lower() for r in result['rows'])


def test_query_transactions_truncates(app, seed_data):
    with app.app_context():
        result = tools.dispatch('query_transactions', {
            'start_date': '2026-01-01', 'end_date': '2026-12-31',
            'limit': 2,
        })
    assert result['count'] == 2
    assert result['truncated'] is True


def test_query_transactions_invalid_date(app, seed_data):
    with app.app_context():
        result = tools.dispatch('query_transactions', {
            'start_date': 'not-a-date', 'end_date': '2026-03-31',
        })
    assert 'error' in result


def test_aggregate_by_month_abs_sum(app, seed_data):
    with app.app_context():
        result = tools.dispatch('aggregate_transactions', {
            'start_date': '2026-01-01', 'end_date': '2026-03-31',
            'group_by': 'month', 'metric': 'abs_sum',
        })
    groups = {g['key']: g['value'] for g in result['groups']}
    # Jan: 15.99 + 82.40 + 34.99 = 133.38
    # Feb: 15.99 + 91.10 + 129.00 = 236.09
    # Mar: 15.99 + 77.05 + 28.75 = 121.79 (excluding payroll +4200)
    assert groups == {'2026-01': 133.38, '2026-02': 236.09, '2026-03': 121.79}


def test_aggregate_by_merchant_count(app, seed_data):
    with app.app_context():
        result = tools.dispatch('aggregate_transactions', {
            'start_date': '2026-01-01', 'end_date': '2026-03-31',
            'group_by': 'merchant', 'metric': 'count',
        })
    groups = {g['key']: g['value'] for g in result['groups']}
    assert groups['Netflix'] == 3
    assert groups['Whole Foods'] == 3
    assert groups['Amazon'] == 2


def test_aggregate_by_institution_net(app, seed_data):
    with app.app_context():
        result = tools.dispatch('aggregate_transactions', {
            'start_date': '2026-01-01', 'end_date': '2026-03-31',
            'group_by': 'institution', 'metric': 'net',
        })
    groups = {g['key']: g['value'] for g in result['groups']}
    # Truist: -(15.99*3) - (82.40+91.10+77.05) = -47.97 - 250.55 = -298.52
    # Amex:  -34.99 - 129.00 + 4200.00 - 28.75 = 4007.26
    assert groups['Truist'] == -298.52
    assert groups['Amex'] == 4007.26


def test_aggregate_invalid_group_by(app, seed_data):
    with app.app_context():
        result = tools.dispatch('aggregate_transactions', {
            'start_date': '2026-01-01', 'end_date': '2026-03-31',
            'group_by': 'galaxy', 'metric': 'sum',
        })
    assert 'error' in result


@freeze_time('2026-05-17')
def test_find_recurring(app, seed_data):
    with app.app_context():
        result = tools.dispatch('find_recurring', {
            'lookback_months': 6,
            'min_occurrences': 3,
            'amount_tolerance': 0.10,
        })
    merchants = {c['merchant']: c for c in result['candidates']}
    assert 'Netflix' in merchants
    assert merchants['Netflix']['occurrences'] == 3
    assert merchants['Netflix']['typical_amount'] == -15.99
    assert 'Whole Foods' in merchants
    assert merchants['Whole Foods']['occurrences'] == 3
    # Amazon has 2 occurrences, below threshold of 3
    assert 'Amazon' not in merchants


@freeze_time('2026-05-17')
def test_find_recurring_amount_tolerance(app, seed_data):
    # Whole Foods amounts: 82.40, 91.10, 77.05. Spread is 91.10/77.05 = 1.182 > 1.10.
    # With tight tolerance 0.05 these are too spread to count as recurring.
    with app.app_context():
        result = tools.dispatch('find_recurring', {
            'lookback_months': 6,
            'min_occurrences': 3,
            'amount_tolerance': 0.05,
        })
    merchants = {c['merchant']: c for c in result['candidates']}
    assert 'Netflix' in merchants
    assert 'Whole Foods' not in merchants
