# Web App Refactor Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Refactor standalone `setup.py`/`sync.py` scripts into a Flask web app with PostgreSQL, deployed on DigitalOcean App Platform as a single Docker container.

**Architecture:** Flask app factory pattern. SQLAlchemy models with Flask-Migrate for schema management. APScheduler runs daily sync in a background thread inside the single gunicorn worker. All Plaid API calls encapsulated in a `PlaidClient` class. Session-based single-password auth.

**Tech Stack:** Flask 3, Flask-SQLAlchemy 3, Flask-Migrate 4, APScheduler 3, plaid-python 26+, psycopg2-binary, gunicorn, Bootstrap 5 (CDN), pytest, pytest-flask

---

## File Map

| File | Action | Responsibility |
|------|--------|---------------|
| `requirements.txt` | Modify | Add new dependencies |
| `.env.example` | Modify | Add new env vars |
| `app/__init__.py` | Create | App factory, db/migrate init |
| `app/models.py` | Create | Institution, Transaction, SyncLog models |
| `app/plaid_client.py` | Create | Plaid API wrapper |
| `app/sync.py` | Create | Sync logic (replaces root sync.py) |
| `app/routes.py` | Create | All Flask routes and API endpoints |
| `app/templates/base.html` | Create | Dark nav, layout shell |
| `app/templates/login.html` | Create | Password form |
| `app/templates/index.html` | Create | Transaction list with filters |
| `app/templates/settings.html` | Create | Institution management + sync log |
| `migrations/` | Create | Flask-Migrate generated files |
| `wsgi.py` | Create | Gunicorn entry point + scheduler start |
| `Dockerfile` | Create | Single-container build |
| `tests/conftest.py` | Create | pytest fixtures |
| `tests/test_models.py` | Create | Model unit tests |
| `tests/test_plaid_client.py` | Create | PlaidClient unit tests |
| `tests/test_sync.py` | Create | Sync logic unit tests |
| `tests/test_auth.py` | Create | Auth route tests |
| `tests/test_routes.py` | Create | Route integration tests |
| `setup.py` (root) | Delete | Replaced by web UI |
| `sync.py` (root) | Delete | Replaced by app/sync.py |

---

### Task 1: Update dependencies and scaffold directories

**Files:**
- Modify: `requirements.txt`
- Modify: `.env.example`
- Create dirs: `app/`, `app/templates/`, `tests/`, `migrations/`

- [ ] **Step 1: Update `requirements.txt`**

```
plaid-python>=26.0.0
flask>=3.0.0
flask-sqlalchemy>=3.1.0
flask-migrate>=4.0.0
APScheduler>=3.10.0
psycopg2-binary>=2.9.0
python-dotenv>=1.0.0
gunicorn>=21.0.0
pytest>=8.0.0
pytest-flask>=1.3.0
```

- [ ] **Step 2: Update `.env.example`**

```
# Plaid credentials — https://dashboard.plaid.com/developers/keys
PLAID_CLIENT_ID=
PLAID_SECRET=
PLAID_ENV=development

# Web app
APP_PASSWORD=          # single password to log in to the web UI
SECRET_KEY=            # random 32-char string for session signing

# Database — injected automatically by DO App Platform; set manually for local dev
DATABASE_URL=postgresql://user:pass@localhost:5432/financials
```

- [ ] **Step 3: Create directory structure**

```bash
mkdir -p app/templates tests
touch app/__init__.py app/models.py app/plaid_client.py app/sync.py app/routes.py
touch tests/__init__.py tests/conftest.py
```

- [ ] **Step 4: Install dependencies**

```bash
python3 -m venv venv && source venv/bin/activate
pip install -r requirements.txt
```

Expected: All packages install without errors.

- [ ] **Step 5: Commit**

```bash
git add requirements.txt .env.example app/ tests/
git commit -m "chore: scaffold app package and update dependencies"
```

---

### Task 2: SQLAlchemy models

**Files:**
- Create: `app/models.py`
- Create: `tests/test_models.py`
- Modify: `tests/conftest.py`

- [ ] **Step 1: Write `tests/conftest.py`**

```python
import pytest
from app import create_app
from app.models import db as _db


@pytest.fixture(scope='function')
def app():
    test_config = {
        'TESTING': True,
        'SQLALCHEMY_DATABASE_URI': 'sqlite:///:memory:',
        'APP_PASSWORD': 'testpass',
        'SECRET_KEY': 'test-secret-key',
        'PLAID_CLIENT_ID': 'test-client-id',
        'PLAID_SECRET': 'test-secret',
        'PLAID_ENV': 'sandbox',
    }
    app = create_app(test_config)
    with app.app_context():
        _db.create_all()
        yield app
        _db.session.remove()
        _db.drop_all()


@pytest.fixture(scope='function')
def client(app):
    return app.test_client()


@pytest.fixture(scope='function')
def auth_client(client):
    client.post('/login', data={'password': 'testpass'}, follow_redirects=True)
    return client
```

- [ ] **Step 2: Write `tests/test_models.py`**

```python
from datetime import date
from decimal import Decimal
import pytest
from sqlalchemy.exc import IntegrityError
from app.models import Institution, Transaction, SyncLog
from app.models import db


def make_inst():
    return Institution(
        name='Test Bank', slug='test_bank',
        access_token='access-sandbox-xxx', item_id='item-xxx',
    )


def test_institution_defaults(app):
    inst = make_inst()
    db.session.add(inst)
    db.session.commit()
    assert inst.id is not None
    assert inst.status == 'active'
    assert inst.plaid_cursor == ''
    assert inst.last_synced_at is None


def test_transaction_creation(app):
    inst = make_inst()
    db.session.add(inst)
    db.session.flush()
    txn = Transaction(
        plaid_transaction_id='txn-001',
        institution_id=inst.id,
        account_id='acc-001',
        date=date(2026, 5, 1),
        description='Coffee',
        amount=Decimal('5.00'),
    )
    db.session.add(txn)
    db.session.commit()
    assert txn.id is not None
    assert txn.removed is False


def test_cascade_delete_removes_transactions(app):
    inst = make_inst()
    db.session.add(inst)
    db.session.flush()
    txn = Transaction(
        plaid_transaction_id='txn-002', institution_id=inst.id,
        account_id='acc-001', date=date(2026, 5, 1),
        description='Coffee', amount=Decimal('5.00'),
    )
    db.session.add(txn)
    db.session.commit()

    db.session.delete(inst)
    db.session.commit()

    assert Transaction.query.filter_by(plaid_transaction_id='txn-002').first() is None


def test_plaid_transaction_id_unique(app):
    inst = make_inst()
    db.session.add(inst)
    db.session.flush()
    t1 = Transaction(plaid_transaction_id='dup', institution_id=inst.id,
                     account_id='a', date=date(2026, 5, 1), description='A', amount=Decimal('1'))
    t2 = Transaction(plaid_transaction_id='dup', institution_id=inst.id,
                     account_id='a', date=date(2026, 5, 1), description='B', amount=Decimal('1'))
    db.session.add_all([t1, t2])
    with pytest.raises(IntegrityError):
        db.session.commit()


def test_sync_log_creation(app):
    from datetime import datetime
    inst = make_inst()
    db.session.add(inst)
    db.session.flush()
    log = SyncLog(institution_id=inst.id, started_at=datetime.utcnow(),
                  added_count=5, removed_count=1)
    db.session.add(log)
    db.session.commit()
    assert log.id is not None
    assert log.error is None
```

- [ ] **Step 3: Run tests — expect ImportError (models not written yet)**

```bash
pytest tests/test_models.py -v
```

Expected: `ImportError: cannot import name 'Institution' from 'app.models'`

- [ ] **Step 4: Write `app/models.py`**

```python
from datetime import datetime
from app import db


class Institution(db.Model):
    __tablename__ = 'institutions'

    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(255), nullable=False)
    slug = db.Column(db.String(255), unique=True, nullable=False)
    access_token = db.Column(db.String(255), nullable=False)
    item_id = db.Column(db.String(255), nullable=False)
    plaid_cursor = db.Column(db.Text, default='', nullable=False)
    status = db.Column(db.String(50), default='active', nullable=False)
    last_synced_at = db.Column(db.DateTime, nullable=True)
    created_at = db.Column(db.DateTime, default=datetime.utcnow, nullable=False)

    transactions = db.relationship(
        'Transaction', backref='institution', lazy=True, cascade='all, delete-orphan'
    )
    sync_logs = db.relationship('SyncLog', backref='institution', lazy=True)


class Transaction(db.Model):
    __tablename__ = 'transactions'

    id = db.Column(db.Integer, primary_key=True)
    plaid_transaction_id = db.Column(db.String(255), unique=True, nullable=False)
    institution_id = db.Column(
        db.Integer, db.ForeignKey('institutions.id', ondelete='CASCADE'), nullable=False
    )
    account_id = db.Column(db.String(255), nullable=False)
    date = db.Column(db.Date, nullable=False)
    description = db.Column(db.String(512), nullable=False)
    merchant_name = db.Column(db.String(255), nullable=True)
    amount = db.Column(db.Numeric(10, 2), nullable=False)
    category = db.Column(db.String(255), nullable=True)
    removed = db.Column(db.Boolean, default=False, nullable=False)
    created_at = db.Column(db.DateTime, default=datetime.utcnow, nullable=False)
    updated_at = db.Column(
        db.DateTime, default=datetime.utcnow, onupdate=datetime.utcnow, nullable=False
    )


class SyncLog(db.Model):
    __tablename__ = 'sync_logs'

    id = db.Column(db.Integer, primary_key=True)
    institution_id = db.Column(
        db.Integer, db.ForeignKey('institutions.id', ondelete='SET NULL'), nullable=True
    )
    started_at = db.Column(db.DateTime, default=datetime.utcnow, nullable=False)
    completed_at = db.Column(db.DateTime, nullable=True)
    added_count = db.Column(db.Integer, default=0, nullable=False)
    removed_count = db.Column(db.Integer, default=0, nullable=False)
    error = db.Column(db.Text, nullable=True)
```

- [ ] **Step 5: Write minimal `app/__init__.py` (enough for tests to import)**

```python
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
```

- [ ] **Step 6: Run tests — expect all pass**

```bash
pytest tests/test_models.py -v
```

Expected: 5 tests pass.

- [ ] **Step 7: Commit**

```bash
git add app/__init__.py app/models.py tests/conftest.py tests/test_models.py
git commit -m "feat: add SQLAlchemy models and app factory"
```

---

### Task 3: Flask-Migrate database setup

**Files:**
- Create: `migrations/` (generated by Flask-Migrate)

- [ ] **Step 1: Create a minimal `app/routes.py` (stub — full routes come in Task 7)**

```python
from flask import Blueprint

bp = Blueprint('main', __name__)
```

- [ ] **Step 2: Create `wsgi.py` stub**

```python
from app import create_app

app = create_app()
```

- [ ] **Step 3: Initialize Flask-Migrate**

```bash
flask --app wsgi db init
```

Expected: `migrations/` directory created with `alembic.ini`, `env.py`, `versions/`.

- [ ] **Step 4: Generate initial migration**

```bash
flask --app wsgi db migrate -m "initial schema"
```

Expected: A file created at `migrations/versions/<hash>_initial_schema.py`. Open it and verify it contains `op.create_table` calls for `institutions`, `transactions`, and `sync_logs`.

- [ ] **Step 5: Apply migration locally**

```bash
flask --app wsgi db upgrade
```

Expected: `Running upgrade  -> <hash>, initial schema` with no errors. A `financials.db` SQLite file is created (or tables created in your local postgres if DATABASE_URL is set).

- [ ] **Step 6: Commit**

```bash
git add migrations/ wsgi.py app/routes.py
git commit -m "feat: add Flask-Migrate setup and initial schema migration"
```

---

### Task 4: Plaid client wrapper

**Files:**
- Create: `app/plaid_client.py`
- Create: `tests/test_plaid_client.py`

- [ ] **Step 1: Write `tests/test_plaid_client.py`**

```python
import json
from unittest.mock import MagicMock, patch
import pytest
import plaid
from app.plaid_client import PlaidClient, slugify


def test_slugify():
    assert slugify('American Express') == 'american_express'
    assert slugify('Citi Bank') == 'citi_bank'
    assert slugify('Truist') == 'truist'
    assert slugify('U.S. Bank') == 'u_s_bank'


def _make_client():
    return PlaidClient({
        'PLAID_CLIENT_ID': 'test-id',
        'PLAID_SECRET': 'test-secret',
        'PLAID_ENV': 'sandbox',
    })


@patch('app.plaid_client.plaid_api.PlaidApi')
def test_create_link_token(MockApi):
    mock_response = MagicMock()
    mock_response.link_token = 'link-sandbox-xyz'
    MockApi.return_value.link_token_create.return_value = mock_response

    client = _make_client()
    client._client = MockApi.return_value
    assert client.create_link_token() == 'link-sandbox-xyz'


@patch('app.plaid_client.plaid_api.PlaidApi')
def test_exchange_token(MockApi):
    api = MockApi.return_value
    api.item_public_token_exchange.return_value = MagicMock(
        access_token='access-sandbox-abc', item_id='item-123'
    )
    api.item_get.return_value = MagicMock(item=MagicMock(institution_id='ins_10'))
    api.institutions_get_by_id.return_value = MagicMock(
        institution=MagicMock(name='American Express')
    )

    client = _make_client()
    client._client = api
    access_token, item_id, name, slug = client.exchange_token('public-token-xxx')

    assert access_token == 'access-sandbox-abc'
    assert item_id == 'item-123'
    assert name == 'American Express'
    assert slug == 'american_express'


@patch('app.plaid_client.plaid_api.PlaidApi')
def test_sync_transactions_handles_pagination(MockApi):
    page1 = MagicMock(
        added=[MagicMock(transaction_id='t1')], modified=[], removed=[],
        next_cursor='cursor-2', has_more=True
    )
    page2 = MagicMock(
        added=[MagicMock(transaction_id='t2')], modified=[], removed=[],
        next_cursor='cursor-final', has_more=False
    )
    api = MockApi.return_value
    api.transactions_sync.side_effect = [page1, page2]

    client = _make_client()
    client._client = api
    added, modified, removed, cursor = client.sync_transactions('access-token', '')

    assert len(added) == 2
    assert cursor == 'cursor-final'
    assert api.transactions_sync.call_count == 2


def test_get_error_code():
    e = MagicMock(spec=plaid.ApiException)
    e.body = json.dumps({'error_code': 'ITEM_LOGIN_REQUIRED'})
    assert PlaidClient.get_error_code(e) == 'ITEM_LOGIN_REQUIRED'


def test_get_error_code_invalid_body():
    e = MagicMock(spec=plaid.ApiException)
    e.body = 'not-json'
    assert PlaidClient.get_error_code(e) == ''
```

- [ ] **Step 2: Run tests — expect ImportError**

```bash
pytest tests/test_plaid_client.py -v
```

Expected: `ImportError: cannot import name 'PlaidClient' from 'app.plaid_client'`

- [ ] **Step 3: Write `app/plaid_client.py`**

```python
import json
import re
import plaid
from plaid.api import plaid_api
from plaid.model.link_token_create_request import LinkTokenCreateRequest
from plaid.model.link_token_create_request_user import LinkTokenCreateRequestUser
from plaid.model.products import Products
from plaid.model.country_code import CountryCode
from plaid.model.item_public_token_exchange_request import ItemPublicTokenExchangeRequest
from plaid.model.item_get_request import ItemGetRequest
from plaid.model.item_remove_request import ItemRemoveRequest
from plaid.model.institutions_get_by_id_request import InstitutionsGetByIdRequest
from plaid.model.transactions_sync_request import TransactionsSyncRequest
from plaid.model.transactions_sync_request_options import TransactionsSyncRequestOptions


def slugify(name):
    name = name.lower()
    name = re.sub(r'[^a-z0-9]+', '_', name)
    return name.strip('_')


class PlaidClient:
    def __init__(self, config):
        env = config.get('PLAID_ENV', 'development')
        host = plaid.Environment.Development if env == 'development' else plaid.Environment.Sandbox
        configuration = plaid.Configuration(
            host=host,
            api_key={
                'clientId': config['PLAID_CLIENT_ID'],
                'secret': config['PLAID_SECRET'],
            },
        )
        self._client = plaid_api.PlaidApi(plaid.ApiClient(configuration))

    def create_link_token(self):
        response = self._client.link_token_create(
            LinkTokenCreateRequest(
                products=[Products('transactions')],
                client_name='Financial Sync',
                country_codes=[CountryCode('US')],
                language='en',
                user=LinkTokenCreateRequestUser(client_user_id='local-user'),
            )
        )
        return response.link_token

    def exchange_token(self, public_token):
        exchange_resp = self._client.item_public_token_exchange(
            ItemPublicTokenExchangeRequest(public_token=public_token)
        )
        access_token = exchange_resp.access_token
        item_id = exchange_resp.item_id

        item_resp = self._client.item_get(ItemGetRequest(access_token=access_token))
        institution_id = item_resp.item.institution_id

        inst_resp = self._client.institutions_get_by_id(
            InstitutionsGetByIdRequest(
                institution_id=institution_id,
                country_codes=[CountryCode('US')],
            )
        )
        name = inst_resp.institution.name
        return access_token, item_id, name, slugify(name)

    def remove_item(self, access_token):
        self._client.item_remove(ItemRemoveRequest(access_token=access_token))

    def sync_transactions(self, access_token, cursor=''):
        added, modified, removed = [], [], []
        while True:
            response = self._client.transactions_sync(
                TransactionsSyncRequest(
                    access_token=access_token,
                    cursor=cursor,
                    options=TransactionsSyncRequestOptions(
                        include_personal_finance_category=True,
                    ),
                )
            )
            added.extend(response.added)
            modified.extend(response.modified)
            removed.extend(response.removed)
            cursor = response.next_cursor
            if not response.has_more:
                break
        return added, modified, removed, cursor

    @staticmethod
    def get_error_code(api_exception):
        try:
            return json.loads(api_exception.body).get('error_code', '')
        except Exception:
            return ''
```

- [ ] **Step 4: Run tests — expect all pass**

```bash
pytest tests/test_plaid_client.py -v
```

Expected: 6 tests pass.

- [ ] **Step 5: Commit**

```bash
git add app/plaid_client.py tests/test_plaid_client.py
git commit -m "feat: add PlaidClient wrapper with sync, exchange, and remove"
```

---

### Task 5: Sync logic

**Files:**
- Create: `app/sync.py`
- Create: `tests/test_sync.py`

- [ ] **Step 1: Write `tests/test_sync.py`**

```python
from datetime import date
from decimal import Decimal
from unittest.mock import MagicMock, patch
from app.models import Institution, Transaction, SyncLog
from app.models import db
from app.sync import sync_all_institutions, _upsert_transactions, _mark_removed


def _make_institution(app):
    with app.app_context():
        inst = Institution(
            name='Test Bank', slug='test_bank',
            access_token='access-test', item_id='item-test',
        )
        db.session.add(inst)
        db.session.commit()
        return inst.id


def _mock_txn(txn_id, amount=5.00, txn_date=None):
    txn = MagicMock()
    txn.transaction_id = txn_id
    txn.account_id = 'acc-001'
    txn.date = txn_date or date(2026, 5, 1)
    txn.name = 'Test Merchant'
    txn.merchant_name = 'Test Merchant'
    txn.amount = amount
    txn.personal_finance_category = MagicMock()
    txn.personal_finance_category.primary = 'FOOD_AND_DRINK'
    return txn


def test_upsert_adds_new_transactions(app):
    inst_id = _make_institution(app)
    with app.app_context():
        txns = [_mock_txn('txn-001'), _mock_txn('txn-002')]
        count = _upsert_transactions(inst_id, txns)
        db.session.commit()
        assert count == 2
        assert Transaction.query.count() == 2


def test_upsert_updates_existing_transaction(app):
    inst_id = _make_institution(app)
    with app.app_context():
        _upsert_transactions(inst_id, [_mock_txn('txn-001', amount=5.00)])
        db.session.commit()

        count = _upsert_transactions(inst_id, [_mock_txn('txn-001', amount=6.00)])
        db.session.commit()

        assert count == 0  # no new rows
        stored = Transaction.query.filter_by(plaid_transaction_id='txn-001').first()
        assert stored.amount == Decimal('6.00')


def test_mark_removed_flags_transactions(app):
    inst_id = _make_institution(app)
    with app.app_context():
        _upsert_transactions(inst_id, [_mock_txn('txn-001'), _mock_txn('txn-002')])
        db.session.commit()

        removed = [MagicMock(transaction_id='txn-001')]
        count = _mark_removed(removed)
        db.session.commit()

        assert count == 1
        assert Transaction.query.filter_by(plaid_transaction_id='txn-001').first().removed is True
        assert Transaction.query.filter_by(plaid_transaction_id='txn-002').first().removed is False


@patch('app.sync.PlaidClient')
def test_sync_all_institutions_happy_path(MockPlaidClient, app):
    inst_id = _make_institution(app)
    with app.app_context():
        mock_client = MagicMock()
        mock_client.sync_transactions.return_value = (
            [_mock_txn('txn-new')], [], [], 'new-cursor'
        )
        MockPlaidClient.return_value = mock_client

        sync_all_institutions()

        inst = Institution.query.get(inst_id)
        assert inst.plaid_cursor == 'new-cursor'
        assert inst.last_synced_at is not None
        assert inst.status == 'active'
        assert Transaction.query.count() == 1
        log = SyncLog.query.first()
        assert log.added_count == 1
        assert log.error is None


@patch('app.sync.PlaidClient')
def test_sync_sets_login_required_on_error(MockPlaidClient, app):
    import json
    import plaid

    inst_id = _make_institution(app)
    with app.app_context():
        mock_client = MagicMock()
        api_exc = plaid.ApiException(status=400)
        api_exc.body = json.dumps({'error_code': 'ITEM_LOGIN_REQUIRED', 'error_message': 'test'})
        mock_client.sync_transactions.side_effect = api_exc
        MockPlaidClient.return_value = mock_client

        sync_all_institutions()

        inst = Institution.query.get(inst_id)
        assert inst.status == 'login_required'
        log = SyncLog.query.first()
        assert log.error is not None
```

- [ ] **Step 2: Run tests — expect ImportError**

```bash
pytest tests/test_sync.py -v
```

Expected: `ImportError: cannot import name 'sync_all_institutions' from 'app.sync'`

- [ ] **Step 3: Write `app/sync.py`**

```python
from datetime import datetime
from decimal import Decimal
import plaid
from flask import current_app
from app.models import db, Institution, Transaction, SyncLog
from app.plaid_client import PlaidClient


def sync_all_institutions():
    """Sync all active institutions. Must be called within an app context."""
    config = current_app.config
    client = PlaidClient(config)
    institutions = Institution.query.filter_by(status='active').all()
    for institution in institutions:
        _sync_institution(client, institution)


def _sync_institution(client, institution):
    log = SyncLog(institution_id=institution.id, started_at=datetime.utcnow())
    db.session.add(log)

    try:
        added, modified, removed, new_cursor = client.sync_transactions(
            institution.access_token, institution.plaid_cursor
        )
        added_count = _upsert_transactions(institution.id, added + modified)
        removed_count = _mark_removed(removed)

        institution.plaid_cursor = new_cursor
        institution.last_synced_at = datetime.utcnow()
        institution.status = 'active'

        log.completed_at = datetime.utcnow()
        log.added_count = added_count
        log.removed_count = removed_count

    except plaid.ApiException as e:
        code = PlaidClient.get_error_code(e)
        if code == 'ITEM_LOGIN_REQUIRED':
            institution.status = 'login_required'
        log.error = f'{code}: {e}'

    db.session.commit()


def _upsert_transactions(institution_id, transactions):
    new_count = 0
    for txn in transactions:
        category = ''
        if getattr(txn, 'personal_finance_category', None):
            category = txn.personal_finance_category.primary
        elif getattr(txn, 'category', None):
            category = txn.category[0] if txn.category else ''

        existing = Transaction.query.filter_by(
            plaid_transaction_id=txn.transaction_id
        ).first()

        if existing:
            existing.description = txn.name or ''
            existing.merchant_name = txn.merchant_name or ''
            existing.amount = Decimal(str(txn.amount))
            existing.category = category
            existing.removed = False
            existing.updated_at = datetime.utcnow()
        else:
            db.session.add(Transaction(
                plaid_transaction_id=txn.transaction_id,
                institution_id=institution_id,
                account_id=txn.account_id,
                date=txn.date,
                description=txn.name or '',
                merchant_name=txn.merchant_name or '',
                amount=Decimal(str(txn.amount)),
                category=category,
            ))
            new_count += 1

    return new_count


def _mark_removed(removed_transactions):
    count = 0
    for removed_txn in removed_transactions:
        txn = Transaction.query.filter_by(
            plaid_transaction_id=removed_txn.transaction_id
        ).first()
        if txn and not txn.removed:
            txn.removed = True
            txn.updated_at = datetime.utcnow()
            count += 1
    return count
```

- [ ] **Step 4: Run tests — expect all pass**

```bash
pytest tests/test_sync.py -v
```

Expected: 6 tests pass.

- [ ] **Step 5: Commit**

```bash
git add app/sync.py tests/test_sync.py
git commit -m "feat: add sync logic with upsert and removed-transaction handling"
```

---

### Task 6: Auth routes + tests

**Files:**
- Modify: `app/routes.py`
- Create: `tests/test_auth.py`

- [ ] **Step 1: Write `tests/test_auth.py`**

```python
def test_index_redirects_to_login_when_unauthenticated(client):
    res = client.get('/')
    assert res.status_code == 302
    assert '/login' in res.headers['Location']

def test_settings_redirects_to_login_when_unauthenticated(client):
    res = client.get('/settings')
    assert res.status_code == 302
    assert '/login' in res.headers['Location']

def test_login_correct_password_redirects_to_index(client):
    res = client.post('/login', data={'password': 'testpass'}, follow_redirects=True)
    assert res.status_code == 200

def test_login_wrong_password_shows_error(client):
    res = client.post('/login', data={'password': 'wrong'}, follow_redirects=True)
    assert b'Incorrect password' in res.data

def test_logout_clears_session(auth_client):
    auth_client.get('/logout')
    res = auth_client.get('/')
    assert res.status_code == 302
    assert '/login' in res.headers['Location']
```

- [ ] **Step 2: Run tests — expect failures (routes stub has no login route)**

```bash
pytest tests/test_auth.py -v
```

Expected: All 5 fail with 404 or AssertionError.

- [ ] **Step 3: Write full `app/routes.py` (all routes — page routes, API routes, auth)**

```python
from functools import wraps
from datetime import datetime
import threading

from flask import (
    Blueprint, render_template, request, redirect,
    url_for, session, jsonify, current_app,
)

from app.models import db, Institution, Transaction, SyncLog

bp = Blueprint('main', __name__)


def login_required(f):
    @wraps(f)
    def decorated(*args, **kwargs):
        if not session.get('authenticated'):
            return redirect(url_for('main.login'))
        return f(*args, **kwargs)
    return decorated


# ── Auth ──────────────────────────────────────────────────────────────────────

@bp.route('/login', methods=['GET', 'POST'])
def login():
    if request.method == 'POST':
        if request.form.get('password') == current_app.config['APP_PASSWORD']:
            session['authenticated'] = True
            return redirect(url_for('main.index'))
        return render_template('login.html', error='Incorrect password')
    return render_template('login.html', error=None)


@bp.route('/logout')
def logout():
    session.clear()
    return redirect(url_for('main.login'))


# ── Pages ─────────────────────────────────────────────────────────────────────

@bp.route('/')
@login_required
def index():
    page = request.args.get('page', 1, type=int)
    institution_id = request.args.get('institution', type=int)
    month = request.args.get('month', '')

    query = Transaction.query.filter_by(removed=False)
    if institution_id:
        query = query.filter_by(institution_id=institution_id)
    if month:
        try:
            year, mon = int(month[:4]), int(month[5:7])
            from datetime import date
            next_year = year + 1 if mon == 12 else year
            next_mon = 1 if mon == 12 else mon + 1
            query = query.filter(
                Transaction.date >= date(year, mon, 1),
                Transaction.date < date(next_year, next_mon, 1),
            )
        except (ValueError, IndexError):
            pass

    transactions = query.order_by(Transaction.date.desc()).paginate(
        page=page, per_page=50, error_out=False
    )
    institutions = Institution.query.order_by(Institution.name).all()
    return render_template(
        'index.html',
        transactions=transactions,
        institutions=institutions,
        selected_institution=institution_id,
        selected_month=month,
    )


@bp.route('/settings')
@login_required
def settings():
    institutions = Institution.query.order_by(Institution.name).all()
    sync_logs = SyncLog.query.order_by(SyncLog.started_at.desc()).limit(50).all()
    return render_template('settings.html', institutions=institutions, sync_logs=sync_logs)


# ── Plaid API ─────────────────────────────────────────────────────────────────

@bp.route('/api/plaid/create_link_token', methods=['POST'])
@login_required
def create_link_token():
    from app.plaid_client import PlaidClient
    client = PlaidClient(current_app.config)
    try:
        return jsonify({'link_token': client.create_link_token()})
    except Exception as e:
        return jsonify({'error': str(e)}), 400


@bp.route('/api/plaid/exchange_token', methods=['POST'])
@login_required
def exchange_token():
    from app.plaid_client import PlaidClient
    client = PlaidClient(current_app.config)
    try:
        access_token, item_id, name, slug = client.exchange_token(
            request.json['public_token']
        )
        if Institution.query.filter_by(slug=slug).first():
            return jsonify({'error': f'{name} is already connected'}), 400

        inst = Institution(
            name=name, slug=slug,
            access_token=access_token, item_id=item_id,
        )
        db.session.add(inst)
        db.session.commit()
        return jsonify({'name': name, 'id': inst.id})
    except Exception as e:
        return jsonify({'error': str(e)}), 400


@bp.route('/api/plaid/remove/<int:institution_id>', methods=['POST'])
@login_required
def remove_institution(institution_id):
    from app.plaid_client import PlaidClient
    inst = Institution.query.get_or_404(institution_id)
    try:
        PlaidClient(current_app.config).remove_item(inst.access_token)
    except Exception:
        pass  # clean up locally even if Plaid call fails
    db.session.delete(inst)
    db.session.commit()
    return jsonify({'status': 'ok'})


# ── Sync API ──────────────────────────────────────────────────────────────────

@bp.route('/api/sync', methods=['POST'])
@login_required
def trigger_sync():
    from app.sync import sync_all_institutions
    app = current_app._get_current_object()

    def run():
        with app.app_context():
            sync_all_institutions()

    threading.Thread(target=run, daemon=True).start()
    return jsonify({'status': 'started'})


@bp.route('/api/sync/status')
@login_required
def sync_status():
    last_log = SyncLog.query.order_by(SyncLog.started_at.desc()).first()
    institutions = Institution.query.order_by(Institution.name).all()
    return jsonify({
        'last_sync': last_log.started_at.isoformat() if last_log else None,
        'institutions': [
            {
                'id': i.id,
                'name': i.name,
                'status': i.status,
                'last_synced_at': i.last_synced_at.isoformat() if i.last_synced_at else None,
            }
            for i in institutions
        ],
    })
```

- [ ] **Step 4: Run auth tests — expect all pass**

```bash
pytest tests/test_auth.py -v
```

Expected: 5 tests pass.

- [ ] **Step 5: Commit**

```bash
git add app/routes.py tests/test_auth.py
git commit -m "feat: add all routes with auth, Plaid API, and sync endpoints"
```

---

### Task 7: Route integration tests

**Files:**
- Create: `tests/test_routes.py`

- [ ] **Step 1: Write `tests/test_routes.py`**

```python
from datetime import date
from decimal import Decimal
from unittest.mock import MagicMock, patch
from app.models import Institution, Transaction, SyncLog
from app.models import db


def _make_institution(app, name='Test Bank', slug='test_bank'):
    with app.app_context():
        inst = Institution(
            name=name, slug=slug,
            access_token='access-test', item_id='item-test',
        )
        db.session.add(inst)
        db.session.commit()
        return inst.id


def _make_transaction(app, inst_id, plaid_id='txn-001', description='Starbucks'):
    with app.app_context():
        txn = Transaction(
            plaid_transaction_id=plaid_id,
            institution_id=inst_id,
            account_id='acc-001',
            date=date(2026, 5, 1),
            description=description,
            amount=Decimal('6.75'),
        )
        db.session.add(txn)
        db.session.commit()


def test_index_shows_transactions(auth_client, app):
    inst_id = _make_institution(app)
    _make_transaction(app, inst_id)
    res = auth_client.get('/')
    assert res.status_code == 200
    assert b'Starbucks' in res.data


def test_index_filters_by_institution(auth_client, app):
    inst_id = _make_institution(app)
    inst2_id = _make_institution(app, name='Citi', slug='citi')
    _make_transaction(app, inst_id, 'txn-a', 'AmEx Charge')
    _make_transaction(app, inst2_id, 'txn-b', 'Citi Charge')

    res = auth_client.get(f'/?institution={inst_id}')
    assert b'AmEx Charge' in res.data
    assert b'Citi Charge' not in res.data


def test_settings_shows_institutions(auth_client, app):
    _make_institution(app)
    res = auth_client.get('/settings')
    assert res.status_code == 200
    assert b'Test Bank' in res.data


@patch('app.routes.PlaidClient')
def test_create_link_token(MockPlaidClient, auth_client):
    MockPlaidClient.return_value.create_link_token.return_value = 'link-test-token'
    res = auth_client.post('/api/plaid/create_link_token')
    assert res.status_code == 200
    assert res.json['link_token'] == 'link-test-token'


@patch('app.routes.PlaidClient')
def test_exchange_token_creates_institution(MockPlaidClient, auth_client, app):
    MockPlaidClient.return_value.exchange_token.return_value = (
        'access-sandbox-abc', 'item-123', 'American Express', 'american_express'
    )
    res = auth_client.post('/api/plaid/exchange_token',
                           json={'public_token': 'public-test'})
    assert res.status_code == 200
    assert res.json['name'] == 'American Express'

    with app.app_context():
        assert Institution.query.filter_by(slug='american_express').first() is not None


@patch('app.routes.PlaidClient')
def test_exchange_token_rejects_duplicate(MockPlaidClient, auth_client, app):
    _make_institution(app, name='Test Bank', slug='test_bank')
    MockPlaidClient.return_value.exchange_token.return_value = (
        'tok', 'item', 'Test Bank', 'test_bank'
    )
    res = auth_client.post('/api/plaid/exchange_token',
                           json={'public_token': 'pt'})
    assert res.status_code == 400
    assert 'already connected' in res.json['error']


@patch('app.routes.PlaidClient')
def test_remove_institution_deletes_it(MockPlaidClient, auth_client, app):
    inst_id = _make_institution(app)
    res = auth_client.post(f'/api/plaid/remove/{inst_id}')
    assert res.status_code == 200
    with app.app_context():
        assert Institution.query.get(inst_id) is None


def test_sync_status_returns_json(auth_client):
    res = auth_client.get('/api/sync/status')
    assert res.status_code == 200
    data = res.json
    assert 'last_sync' in data
    assert 'institutions' in data
```

- [ ] **Step 2: Run all tests — expect all pass**

```bash
pytest tests/ -v
```

Expected: All tests pass (models + plaid_client + sync + auth + routes).

- [ ] **Step 3: Commit**

```bash
git add tests/test_routes.py
git commit -m "test: add route integration tests"
```

---

### Task 8: HTML templates

**Files:**
- Create: `app/templates/base.html`
- Create: `app/templates/login.html`
- Create: `app/templates/index.html`
- Create: `app/templates/settings.html`

No automated tests for templates — verify visually by running the app locally.

- [ ] **Step 1: Write `app/templates/base.html`**

```html
<!DOCTYPE html>
<html lang="en">
<head>
  <meta charset="UTF-8">
  <meta name="viewport" content="width=device-width, initial-scale=1.0">
  <title>Financials</title>
  <link href="https://cdn.jsdelivr.net/npm/bootstrap@5.3.0/dist/css/bootstrap.min.css" rel="stylesheet">
  <style>
    body { background: #f8fafc; }
    .navbar-brand { color: #60a5fa !important; font-weight: 700; }
  </style>
</head>
<body>
{% if session.get('authenticated') %}
<nav class="navbar navbar-dark bg-dark px-3">
  <a class="navbar-brand" href="/">Financials</a>
  <div class="d-flex align-items-center gap-3">
    <small id="sync-label" class="text-secondary"></small>
    <button id="sync-btn" class="btn btn-sm btn-primary" onclick="triggerSync(this)">Sync now</button>
    <a href="/settings" class="text-secondary text-decoration-none fs-5">⚙</a>
  </div>
</nav>
{% endif %}
<div class="container-fluid py-4 px-4">
  {% block content %}{% endblock %}
</div>
<script src="https://cdn.jsdelivr.net/npm/bootstrap@5.3.0/dist/js/bootstrap.bundle.min.js"></script>
<script>
async function triggerSync(btn) {
  btn.disabled = true;
  btn.textContent = 'Syncing...';
  try {
    await fetch('/api/sync', { method: 'POST' });
    setTimeout(() => location.reload(), 10000);
  } catch (e) {
    btn.disabled = false;
    btn.textContent = 'Sync now';
  }
}
</script>
{% block scripts %}{% endblock %}
</body>
</html>
```

- [ ] **Step 2: Write `app/templates/login.html`**

```html
{% extends 'base.html' %}
{% block content %}
<div class="row justify-content-center mt-5">
  <div class="col-md-4 col-sm-6">
    <div class="card shadow-sm">
      <div class="card-body p-4">
        <h5 class="card-title mb-4 fw-bold" style="color:#60a5fa">Financials</h5>
        {% if error %}
        <div class="alert alert-danger py-2 small">{{ error }}</div>
        {% endif %}
        <form method="post">
          <div class="mb-3">
            <input type="password" name="password" class="form-control"
                   placeholder="Password" autofocus required>
          </div>
          <button type="submit" class="btn btn-primary w-100">Sign in</button>
        </form>
      </div>
    </div>
  </div>
</div>
{% endblock %}
```

- [ ] **Step 3: Write `app/templates/index.html`**

```html
{% extends 'base.html' %}
{% block content %}
<div class="d-flex gap-2 mb-3 flex-wrap">
  <select id="inst-filter" class="form-select form-select-sm w-auto" onchange="applyFilter()">
    <option value="">All institutions</option>
    {% for inst in institutions %}
    <option value="{{ inst.id }}"
      {% if selected_institution == inst.id %}selected{% endif %}>{{ inst.name }}</option>
    {% endfor %}
  </select>
  <input type="month" id="month-filter" class="form-control form-control-sm w-auto"
         value="{{ selected_month }}" onchange="applyFilter()">
  {% if selected_institution or selected_month %}
  <a href="/" class="btn btn-sm btn-outline-secondary">Clear</a>
  {% endif %}
</div>

<div class="card shadow-sm">
  <div class="table-responsive">
    <table class="table table-hover align-middle mb-0">
      <thead class="table-light">
        <tr>
          <th>Date</th><th>Description</th><th>Institution</th>
          <th class="text-end">Amount</th>
        </tr>
      </thead>
      <tbody>
      {% for txn in transactions.items %}
      <tr>
        <td class="text-muted small text-nowrap">{{ txn.date.strftime('%b %d, %Y') }}</td>
        <td>
          {{ txn.description }}
          {% if txn.merchant_name and txn.merchant_name != txn.description %}
          <span class="text-muted small ms-1">· {{ txn.merchant_name }}</span>
          {% endif %}
        </td>
        <td><span class="badge bg-primary">{{ txn.institution.name }}</span></td>
        <td class="text-end text-nowrap
          {% if txn.amount > 0 %}text-danger{% else %}text-success{% endif %}">
          {% if txn.amount > 0 %}-{% else %}+{% endif %}${{ "%.2f"|format(txn.amount|abs) }}
        </td>
      </tr>
      {% else %}
      <tr><td colspan="4" class="text-center text-muted py-5">No transactions found.</td></tr>
      {% endfor %}
      </tbody>
    </table>
  </div>
</div>

{% if transactions.pages > 1 %}
<nav class="mt-3 d-flex justify-content-center">
  <ul class="pagination pagination-sm">
    {% if transactions.has_prev %}
    <li class="page-item">
      <a class="page-link" href="?page={{ transactions.prev_num }}{% if selected_institution %}&institution={{ selected_institution }}{% endif %}{% if selected_month %}&month={{ selected_month }}{% endif %}">«</a>
    </li>
    {% endif %}
    <li class="page-item disabled">
      <span class="page-link">{{ transactions.page }} / {{ transactions.pages }}</span>
    </li>
    {% if transactions.has_next %}
    <li class="page-item">
      <a class="page-link" href="?page={{ transactions.next_num }}{% if selected_institution %}&institution={{ selected_institution }}{% endif %}{% if selected_month %}&month={{ selected_month }}{% endif %}">»</a>
    </li>
    {% endif %}
  </ul>
</nav>
{% endif %}
{% endblock %}

{% block scripts %}
<script>
function applyFilter() {
  const inst = document.getElementById('inst-filter').value;
  const month = document.getElementById('month-filter').value;
  const p = new URLSearchParams();
  if (inst) p.set('institution', inst);
  if (month) p.set('month', month);
  location.href = '/?' + p.toString();
}
</script>
{% endblock %}
```

- [ ] **Step 4: Write `app/templates/settings.html`**

```html
{% extends 'base.html' %}
{% block content %}
<div class="d-flex align-items-center gap-3 mb-4">
  <a href="/" class="text-muted text-decoration-none small">← Transactions</a>
  <h5 class="mb-0">Settings</h5>
</div>

<div class="card shadow-sm mb-4">
  <div class="card-header d-flex justify-content-between align-items-center">
    <span class="fw-medium">Connected Institutions</span>
    <button class="btn btn-primary btn-sm" onclick="connectInstitution()">+ Connect New</button>
  </div>
  <div class="list-group list-group-flush">
    {% for inst in institutions %}
    <div class="list-group-item d-flex align-items-center gap-3" id="inst-row-{{ inst.id }}">
      <div class="flex-grow-1">
        <div class="fw-medium">{{ inst.name }}</div>
        <div class="text-muted small">
          {% if inst.last_synced_at %}
            Last synced {{ inst.last_synced_at.strftime('%b %d at %-I:%M %p') }}
          {% else %}Never synced{% endif %}
          · {{ inst.transactions | length }} transactions
        </div>
      </div>
      {% if inst.status == 'login_required' %}
        <span class="badge bg-warning text-dark">Login required</span>
        <button class="btn btn-sm btn-outline-primary" onclick="connectInstitution()">Re-connect</button>
      {% else %}
        <span class="badge bg-success">Active</span>
      {% endif %}
      <button class="btn btn-sm btn-outline-danger"
              onclick="removeInstitution({{ inst.id }}, '{{ inst.name | e }}')">
        Disconnect
      </button>
    </div>
    {% else %}
    <div class="list-group-item text-muted text-center py-4">
      No institutions connected. Click <strong>+ Connect New</strong> to get started.
    </div>
    {% endfor %}
  </div>
</div>

<div class="card shadow-sm">
  <div class="card-header fw-medium">Sync Log</div>
  <div class="table-responsive">
    <table class="table table-sm align-middle mb-0">
      <thead class="table-light">
        <tr><th>Time</th><th>Institution</th><th>Result</th><th class="text-end">New</th></tr>
      </thead>
      <tbody>
      {% for log in sync_logs %}
      <tr>
        <td class="text-muted small text-nowrap">
          {{ log.started_at.strftime('%b %d, %-I:%M %p') }}
        </td>
        <td>{{ log.institution.name if log.institution else 'All' }}</td>
        <td>
          {% if log.error %}
            <span class="text-danger">✗ {{ log.error[:80] }}</span>
          {% else %}
            <span class="text-success">✓ OK</span>
          {% endif %}
        </td>
        <td class="text-end">{{ log.added_count if not log.error else '—' }}</td>
      </tr>
      {% else %}
      <tr><td colspan="4" class="text-center text-muted py-3">No syncs yet.</td></tr>
      {% endfor %}
      </tbody>
    </table>
  </div>
</div>
{% endblock %}

{% block scripts %}
<script src="https://cdn.plaid.com/link/v2/stable/link-initialize.js"></script>
<script>
async function connectInstitution() {
  const res = await fetch('/api/plaid/create_link_token', { method: 'POST' });
  const { link_token, error } = await res.json();
  if (error) { alert('Error: ' + error); return; }

  Plaid.create({
    token: link_token,
    onSuccess: async (public_token) => {
      const result = await fetch('/api/plaid/exchange_token', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ public_token }),
      });
      const info = await result.json();
      if (info.error) { alert('Error: ' + info.error); return; }
      location.reload();
    },
    onExit: (err) => { if (err) alert(err.display_message || err.error_message || 'Cancelled'); },
  }).open();
}

async function removeInstitution(id, name) {
  if (!confirm(`Disconnect ${name}?\n\nThis will delete all its stored transactions.`)) return;
  const res = await fetch(`/api/plaid/remove/${id}`, { method: 'POST' });
  if (res.ok) {
    document.getElementById(`inst-row-${id}`).remove();
  } else {
    alert('Failed to disconnect. Try again.');
  }
}
</script>
{% endblock %}
```

- [ ] **Step 5: Smoke-test locally**

```bash
export APP_PASSWORD=test SECRET_KEY=dev-key PLAID_CLIENT_ID=x PLAID_SECRET=x
flask --app wsgi run --port 8080
```

Open http://localhost:8080 — verify login page loads, enter "test", verify transaction list renders (empty is fine), navigate to /settings.

- [ ] **Step 6: Commit**

```bash
git add app/templates/
git commit -m "feat: add HTML templates with Bootstrap 5"
```

---

### Task 9: Production entry point and Dockerfile

**Files:**
- Modify: `wsgi.py`
- Create: `Dockerfile`

- [ ] **Step 1: Write final `wsgi.py`**

```python
from app import create_app

app = create_app()


def _start_scheduler():
    from apscheduler.schedulers.background import BackgroundScheduler
    from app.sync import sync_all_institutions

    scheduler = BackgroundScheduler(daemon=True)

    def job():
        with app.app_context():
            sync_all_institutions()

    scheduler.add_job(func=job, trigger='cron', hour=7, minute=0,
                      id='daily_sync', max_instances=1)
    scheduler.start()


_start_scheduler()

if __name__ == '__main__':
    app.run()
```

- [ ] **Step 2: Write `Dockerfile`**

```dockerfile
FROM python:3.12-slim

WORKDIR /app

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY . .

EXPOSE 8080

# Single worker — prevents multiple APScheduler instances running daily sync
CMD ["gunicorn", "wsgi:app", "--bind", "0.0.0.0:8080", "--workers", "1", "--timeout", "120"]
```

- [ ] **Step 3: Build and verify the Docker image**

```bash
docker build -t financials .
```

Expected: Build completes with no errors. Last line: `Successfully tagged financials:latest`

- [ ] **Step 4: Run container locally to verify startup**

```bash
docker run --rm \
  -e APP_PASSWORD=test \
  -e SECRET_KEY=dev-key \
  -e PLAID_CLIENT_ID=x \
  -e PLAID_SECRET=x \
  -e DATABASE_URL=sqlite:///financials.db \
  -p 8080:8080 \
  financials
```

Expected: `[INFO] Listening at: http://0.0.0.0:8080`. Open http://localhost:8080 — login page loads.

- [ ] **Step 5: Commit**

```bash
git add wsgi.py Dockerfile
git commit -m "feat: add production Dockerfile with gunicorn and APScheduler"
```

---

### Task 10: Cleanup and final test run

**Files:**
- Delete: `setup.py` (root)
- Delete: `sync.py` (root)

- [ ] **Step 1: Remove old scripts**

```bash
git rm setup.py sync.py
```

- [ ] **Step 2: Run full test suite**

```bash
pytest tests/ -v
```

Expected: All tests pass. No failures or errors.

- [ ] **Step 3: Commit**

```bash
git commit -m "chore: remove old setup.py and sync.py replaced by web app"
```

---

## Deployment Checklist (DO App Platform)

After all tasks are complete:

1. Push to GitHub main branch
2. In DO App Platform → Create App → Connect GitHub repo
3. DO auto-detects Dockerfile
4. Attach existing managed PostgreSQL cluster → create new database named `financials`
5. Set environment variables in DO dashboard:
   - `PLAID_CLIENT_ID`
   - `PLAID_SECRET`
   - `PLAID_ENV=development`
   - `APP_PASSWORD` (choose a strong password)
   - `SECRET_KEY` (generate with `python -c "import secrets; print(secrets.token_hex(32))"`)
   - `DATABASE_URL` is injected automatically when DB is attached
6. Set Release Command: `flask --app wsgi db upgrade`
7. Deploy — verify app loads at the DO URL
8. Open `/settings` → click "+ Connect New" → complete Plaid Link for each institution
9. Click "Sync now" → verify transactions appear
