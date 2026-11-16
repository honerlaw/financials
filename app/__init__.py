import os
from flask import Flask
from flask_sqlalchemy import SQLAlchemy
from flask_migrate import Migrate

db = SQLAlchemy()
migrate = Migrate()

# Bare schemes that leave the DBAPI choice to SQLAlchemy's default.
_BARE_POSTGRES_SCHEMES = ('postgres://', 'postgresql://')


def _database_url(raw):
    """Name the psycopg2 driver on a bare Postgres URL — pure.

    ``postgres://`` (the Heroku-style form) and ``postgresql://`` (what
    ``.env.example`` documents) both become ``postgresql+psycopg2://``, with the rest
    of the URL — query string included — left as is. Without a named driver,
    SQLAlchemy picks its default DBAPI, and that default changed in 2.1 from
    psycopg2 to psycopg (v3), which this image does not install. This app is
    psycopg2-only unless the URL names a driver itself, so a URL that already
    does (``postgresql+…://``), or is not Postgres at all, passes through
    untouched. Matching is a case-sensitive prefix: both forms are written in
    lowercase, and anything unrecognised is left for SQLAlchemy to reject.
    """
    for scheme in _BARE_POSTGRES_SCHEMES:
        if raw.startswith(scheme):
            return 'postgresql+psycopg2://' + raw[len(scheme):]
    return raw


# A connection older than this is retired at checkout (seconds).
_POOL_RECYCLE_SECONDS = 1800


def _engine_options(db_url):
    """Default pool options for the final database URL — pure.

    The 7am job checks out a connection that may have sat idle since the
    previous day, by which time the server can have closed it (it raised
    "SSL SYSCALL error: EOF detected" and skipped the digest). Pre-ping swaps a
    dead connection for a fresh one at checkout; recycle retires old ones.

    An in-memory SQLite database lives inside its one pooled connection, so
    recycling that connection would silently replace the database with an
    empty one. It gets pre-ping only.
    """
    from sqlalchemy.engine import make_url
    url = make_url(db_url)
    if url.get_backend_name() == 'sqlite' and url.database in (None, '', ':memory:'):
        return {'pool_pre_ping': True}
    return {'pool_pre_ping': True, 'pool_recycle': _POOL_RECYCLE_SECONDS}


def create_app(config=None):
    app = Flask(__name__)

    db_url = _database_url(os.getenv('DATABASE_URL', 'sqlite:///financials.db'))

    app.config.update(
        SQLALCHEMY_DATABASE_URI=db_url,
        SECRET_KEY=os.getenv('SECRET_KEY', ''),
        APP_PASSWORD=os.getenv('APP_PASSWORD', ''),
        SQLALCHEMY_TRACK_MODIFICATIONS=False,
        # The session cookie is the only credential. Lax keeps it off
        # cross-site POSTs, so another site cannot submit the app's forms
        # (rules, sync, digest, institution removal) as the signed-in user.
        SESSION_COOKIE_SAMESITE='Lax',
        PLAID_CLIENT_ID=os.getenv('PLAID_CLIENT_ID', ''),
        PLAID_SECRET=os.getenv('PLAID_SECRET', ''),
        PLAID_ENV=os.getenv('PLAID_ENV', 'development'),
        OPENROUTER_API_KEY=os.getenv('OPENROUTER_API_KEY', ''),
        OPENROUTER_MODEL=os.getenv('OPENROUTER_MODEL', 'anthropic/claude-sonnet-4'),
        OPENROUTER_BASE_URL=os.getenv('OPENROUTER_BASE_URL', 'https://openrouter.ai/api/v1'),
        CHAT_MAX_ITERATIONS=int(os.getenv('CHAT_MAX_ITERATIONS', '10')),
        CHAT_QUERY_ROW_LIMIT=int(os.getenv('CHAT_QUERY_ROW_LIMIT', '200')),
        CHAT_MODELS=[
            m.strip() for m in os.getenv(
                'CHAT_MODELS',
                'anthropic/claude-opus-4.7,anthropic/claude-sonnet-4.6,'
                'openai/gpt-5.5-pro,openai/gpt-5.5,'
                'google/gemini-2.5-pro,x-ai/grok-4.3',
            ).split(',') if m.strip()
        ],
        # Wall-clock timezone for the 7am daily job and the digest's notion of
        # "today" (app/localtime.py). Unset would mean UTC, i.e. a 3am text.
        APP_TIMEZONE=os.getenv('APP_TIMEZONE', 'America/New_York'),
        # Daily digest SMS (app/notifications.py). All four must be set for the
        # digest to activate; missing config soft-disables the feature.
        TWILIO_ACCOUNT_SID=os.getenv('TWILIO_ACCOUNT_SID', ''),
        TWILIO_AUTH_TOKEN=os.getenv('TWILIO_AUTH_TOKEN', ''),
        TWILIO_FROM_NUMBER=os.getenv('TWILIO_FROM_NUMBER', ''),
        BUDGET_ALERT_RECIPIENTS=os.getenv('BUDGET_ALERT_RECIPIENTS', ''),
    )

    if config:
        app.config.update(config)

    # Chosen after the override so they match the URI actually in use. A
    # `config` that sets SQLALCHEMY_ENGINE_OPTIONS replaces them wholesale.
    app.config.setdefault(
        'SQLALCHEMY_ENGINE_OPTIONS',
        _engine_options(app.config['SQLALCHEMY_DATABASE_URI']),
    )

    if not app.config['SECRET_KEY']:
        raise RuntimeError(
            'SECRET_KEY must be set. Generate one with: '
            "python -c 'import secrets; print(secrets.token_hex(32))'"
        )
    if not app.config['APP_PASSWORD']:
        raise RuntimeError('APP_PASSWORD must be set (cannot be empty).')

    db.init_app(app)
    migrate.init_app(app, db)

    from . import models  # noqa: F401 — ensure models registered for migrations
    from .routes import bp
    app.register_blueprint(bp)

    from app.chat.routes import bp as chat_bp
    app.register_blueprint(chat_bp)

    return app
