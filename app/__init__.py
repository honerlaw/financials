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
        SECRET_KEY=os.getenv('SECRET_KEY', 'dev-change-me'),
        APP_PASSWORD=os.getenv('APP_PASSWORD', ''),
        SQLALCHEMY_TRACK_MODIFICATIONS=False,
        PLAID_CLIENT_ID=os.getenv('PLAID_CLIENT_ID', ''),
        PLAID_SECRET=os.getenv('PLAID_SECRET', ''),
        PLAID_ENV=os.getenv('PLAID_ENV', 'development'),
    )

    if config:
        app.config.update(config)

    db.init_app(app)
    migrate.init_app(app, db)

    from . import models  # noqa: F401 — ensure models registered for migrations
    from .routes import bp
    app.register_blueprint(bp)

    return app
