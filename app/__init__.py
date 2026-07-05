import os
from flask import Flask
from flask_sqlalchemy import SQLAlchemy
from flask_migrate import Migrate

db = SQLAlchemy()
migrate = Migrate()


def create_app(config=None):
    app = Flask(__name__)

    db_url = os.getenv('DATABASE_URL', 'sqlite:///financials.db')
    if db_url.startswith('postgres://'):
        db_url = db_url.replace('postgres://', 'postgresql://', 1)

    app.config.update(
        SQLALCHEMY_DATABASE_URI=db_url,
        SECRET_KEY=os.getenv('SECRET_KEY', ''),
        APP_PASSWORD=os.getenv('APP_PASSWORD', ''),
        SQLALCHEMY_TRACK_MODIFICATIONS=False,
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
        # Weekly-budget SMS alerts (app/notifications.py). All four must be set
        # for alerting to activate; missing config soft-disables the feature.
        TWILIO_ACCOUNT_SID=os.getenv('TWILIO_ACCOUNT_SID', ''),
        TWILIO_AUTH_TOKEN=os.getenv('TWILIO_AUTH_TOKEN', ''),
        TWILIO_FROM_NUMBER=os.getenv('TWILIO_FROM_NUMBER', ''),
        BUDGET_ALERT_RECIPIENTS=os.getenv('BUDGET_ALERT_RECIPIENTS', ''),
    )

    if config:
        app.config.update(config)

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
