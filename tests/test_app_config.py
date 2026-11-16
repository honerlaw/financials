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


def test_create_app_pings_and_recycles_pooled_connections():
    """The 7am job must not be handed a connection the server already closed.

    On 2026-11-13 and 2026-11-16 the job's first query hit a pooled Postgres
    connection that had sat idle since the previous day and raised
    ``SSL SYSCALL error: EOF detected``, so neither the sync nor the digest ran.
    """
    app = create_app({'SECRET_KEY': 'x', 'APP_PASSWORD': 'x'})

    options = app.config['SQLALCHEMY_ENGINE_OPTIONS']
    assert options['pool_pre_ping'] is True
    assert options['pool_recycle'] == 1800


@pytest.mark.parametrize('pre_ping', [True, False])
def test_a_pooled_connection_closed_behind_the_pool_is_replaced(tmp_path, pre_ping):
    """Pre-ping swaps a dead pooled connection for a fresh one at checkout.

    A file-backed database is needed: ``:memory:`` gets a StaticPool whose one
    connection *is* the database, so there is nothing to reconnect to. Closing
    the DBAPI connection stands in for the server dropping an idle Postgres
    connection. The ``pre_ping=False`` case proves the test can fail.
    """
    from sqlalchemy import text
    from sqlalchemy.exc import DBAPIError

    config = {
        'SECRET_KEY': 'x',
        'APP_PASSWORD': 'x',
        'SQLALCHEMY_DATABASE_URI': f'sqlite:///{tmp_path / "pool.db"}',
    }
    if not pre_ping:
        # Only the control case overrides; the passing case runs on the
        # engine options create_app ships with.
        config['SQLALCHEMY_ENGINE_OPTIONS'] = {'pool_pre_ping': False}
    app = create_app(config)
    with app.app_context():
        assert db.session.execute(text('select 1')).scalar() == 1
        raw = db.session.connection().connection.dbapi_connection
        db.session.remove()  # return the connection to the pool, still "open"
        raw.close()          # ...but now dead behind the pool's back

        if pre_ping:
            assert db.session.execute(text('select 1')).scalar() == 1
        else:
            with pytest.raises(DBAPIError):
                db.session.execute(text('select 1'))
        db.session.remove()
