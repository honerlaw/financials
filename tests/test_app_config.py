"""The database URL create_app hands SQLAlchemy.

A bare postgres URL must name the psycopg2 driver: SQLAlchemy 2.1 switched the
default DBAPI for ``postgresql://`` to psycopg (v3), which the image does not
install, and the container crashed at ``create_app`` when a build resolved it.
"""
import pytest

from app import _database_url, create_app, db


@pytest.mark.parametrize('raw, expected', [
    ('postgres://u:p@h:25060/db', 'postgresql+psycopg2://u:p@h:25060/db'),
    ('postgresql://u:p@h:25060/db', 'postgresql+psycopg2://u:p@h:25060/db'),
    ('postgresql://u:p@h/db?sslmode=require',
     'postgresql+psycopg2://u:p@h/db?sslmode=require'),
    ('postgresql+psycopg2://u:p@h/db', 'postgresql+psycopg2://u:p@h/db'),
    ('postgresql+psycopg://u:p@h/db', 'postgresql+psycopg://u:p@h/db'),
    ('sqlite:///financials.db', 'sqlite:///financials.db'),
])
def test_database_url_names_psycopg2_on_bare_postgres_urls(raw, expected):
    assert _database_url(raw) == expected


def test_create_app_builds_a_psycopg2_engine_for_a_bare_postgres_url(monkeypatch):
    """No connection is made — the engine imports its DBAPI at creation.

    The URI assertion is the regression guard: under the pinned SQLAlchemy 2.0
    the default driver is already psycopg2, so the dialect assertion would pass
    without ``_database_url``. It only bites under 2.1, where it was checked
    once in a scratch venv (see the work unit's scratchpad).
    """
    monkeypatch.setenv('DATABASE_URL', 'postgresql://u:p@h/d?sslmode=require')
    app = create_app({'SECRET_KEY': 'x', 'APP_PASSWORD': 'x'})

    assert app.config['SQLALCHEMY_DATABASE_URI'] == \
        'postgresql+psycopg2://u:p@h/d?sslmode=require'
    with app.app_context():
        assert db.engine.dialect.driver == 'psycopg2'
