from datetime import date

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
