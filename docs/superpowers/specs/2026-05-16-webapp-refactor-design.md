# Web App Refactor Design

**Date:** 2026-05-16  
**Status:** Approved

## Context

The current tool is two standalone Python scripts (`setup.py` and `sync.py`) that store Plaid access tokens in `.env` and transactions in local CSV files. This works fine on a single machine but has no UI, no remote access, and no database. The goal is to refactor it into a deployable web application that:

- Runs on DigitalOcean App Platform as a single container
- Stores everything in a managed PostgreSQL database
- Exposes a simple web UI for viewing transactions, managing Plaid connections, triggering syncs, and reviewing sync history
- Is forward-compatible with future AI analysis and scheduled email/SMS reports

---

## Architecture

Single Flask web service. One Docker image. No separate worker process — APScheduler runs the daily sync inside the web process.

```
financials/
├── app/
│   ├── __init__.py         # app factory, APScheduler init, auth setup
│   ├── models.py           # SQLAlchemy models: Institution, Transaction, SyncLog
│   ├── routes.py           # all Flask routes + API endpoints
│   ├── plaid_client.py     # Plaid API wrapper (create_link_token, exchange_token, item_remove, sync)
│   ├── sync.py             # sync logic (adapted from current sync.py, writes to DB not CSV)
│   └── templates/
│       ├── base.html       # dark top nav, session-aware
│       ├── index.html      # transaction list (main page)
│       ├── settings.html   # institutions + sync log
│       └── login.html      # password form
├── migrations/             # Alembic migration files
├── Dockerfile
├── wsgi.py                 # gunicorn entry point
├── requirements.txt
└── .env.example
```

---

## Database Schema

### `institutions`
| Column | Type | Notes |
|--------|------|-------|
| id | integer PK | |
| name | varchar | e.g. "American Express" |
| slug | varchar unique | e.g. "american_express" |
| access_token | varchar | Plaid access token |
| item_id | varchar | Plaid item_id (for support/orphan recovery) |
| plaid_cursor | text | Incremental sync cursor, empty string on first run |
| status | varchar | `active` or `login_required` |
| last_synced_at | timestamp | Nullable |
| created_at | timestamp | |

### `transactions`
| Column | Type | Notes |
|--------|------|-------|
| id | integer PK | |
| plaid_transaction_id | varchar unique | Plaid's stable ID |
| institution_id | integer FK | → institutions.id, ON DELETE CASCADE |
| account_id | varchar | Plaid account_id |
| date | date | |
| description | varchar | txn.name from Plaid |
| merchant_name | varchar | Nullable |
| amount | numeric(10,2) | Positive = debit, negative = credit (Plaid convention) |
| category | varchar | personal_finance_category.primary if available |
| removed | boolean | Default false; true if Plaid marks it removed |
| created_at | timestamp | |
| updated_at | timestamp | |

### `sync_logs`
| Column | Type | Notes |
|--------|------|-------|
| id | integer PK | |
| institution_id | integer FK | Nullable (null = all-institution run) |
| started_at | timestamp | |
| completed_at | timestamp | Nullable |
| added_count | integer | Default 0 |
| removed_count | integer | Default 0 |
| error | text | Nullable; stores error message if sync failed |

---

## Routes

### Pages
| Route | Description |
|-------|-------------|
| `GET /` | Transaction list. Filterable by institution and date range. Paginated. Requires auth. |
| `GET /settings` | Institution list + sync log. Requires auth. |
| `GET /login` | Password form |
| `POST /login` | Sets session cookie on correct password, redirects to `/` |
| `GET /logout` | Clears session, redirects to `/login` |

### API endpoints (JSON)
| Route | Description |
|-------|-------------|
| `POST /api/plaid/create_link_token` | Returns a Plaid link_token for the frontend Link flow |
| `POST /api/plaid/exchange_token` | Receives public_token, exchanges for access_token, saves institution to DB |
| `POST /api/plaid/remove/<int:institution_id>` | Calls Plaid item/remove, deletes institution + cascades |
| `POST /api/sync` | Triggers an immediate sync of all institutions, returns job id |
| `GET /api/sync/status` | Returns last sync time and per-institution status |

---

## UI

### Main page (`/`)
- Dark top nav: "Financials" wordmark on left; "Last synced: X ago" + "Sync now" button + ⚙ gear link on right
- Transaction table: Date | Description | Institution (colored badge) | Amount
- Filter bar: institution dropdown + month selector
- Paginated, 50 rows per page, newest first

### Settings page (`/settings`)
- **Connected Institutions** section with "+ Connect New" button
  - Each row: name, last synced time, transaction count, status badge, Disconnect button
  - `login_required` status shows amber badge + "Re-connect" button instead
  - "+ Connect New" triggers Plaid Link popup via `/api/plaid/create_link_token`
- **Sync Log** section below: Time | Institution | Result | New transactions added

### Login page (`/login`)
- Minimal centered form: password field + submit button

---

## Auth

Single-password session auth. `APP_PASSWORD` env var is checked on `POST /login`. On success, `session['authenticated'] = True` is set. All non-login routes require this flag; missing redirects to `/login`. Flask `SECRET_KEY` env var signs the session cookie.

---

## Background Sync

APScheduler `BackgroundScheduler` starts when the Flask app starts. One job: `sync_all_institutions()` runs daily at 7:00 UTC. The same function is called by `POST /api/sync` for on-demand runs. Concurrent runs are prevented by an APScheduler `max_instances=1` setting.

`sync_all_institutions()` iterates over all `active` institutions, calls Plaid `transactions/sync` with cursor pagination, upserts to `transactions`, updates `institutions.plaid_cursor` and `last_synced_at`, and writes a `sync_logs` row.

---

## Deployment

**Dockerfile:** `python:3.12-slim`, installs dependencies, runs `gunicorn wsgi:app --bind 0.0.0.0:8080 --workers 2`.

**DO App Platform:**
- Source: GitHub repo, auto-deploy on push to `main`
- Component type: Web Service
- Run Command: gunicorn (from Dockerfile)
- Release Command: `alembic upgrade head` (runs before each deploy, applies migrations)
- Database: attach existing managed PostgreSQL cluster, create a new database named `financials`. DO injects `DATABASE_URL` automatically.

**Environment variables (set in DO dashboard):**
```
PLAID_CLIENT_ID=
PLAID_SECRET=
PLAID_ENV=development
APP_PASSWORD=
SECRET_KEY=           # random 32-char string
DATABASE_URL=         # injected by DO when DB is attached; set manually for local dev
```

---

## Migration from Current Scripts

The existing `setup.py` and `sync.py` scripts can be deleted after deploy. The Plaid tokens currently in `.env` need to be re-connected through the web UI (run the Plaid Link flow once per institution after first deploy). Historical CSV data in `data/` is not migrated — Plaid's first sync will pull ~24 months of history automatically.

---

## Forward Compatibility

- AI analysis: new `analyses` table, new route `POST /api/analyze`, calls Claude API with transaction data
- Scheduled reports: new `report_schedules` table, APScheduler jobs created dynamically per schedule, sends via SendGrid or Twilio
- Both additions are new tables + new routes — no changes to the three core tables

---

## Verification

1. `docker build -t financials .` — image builds cleanly
2. `docker run -e DATABASE_URL=... -e APP_PASSWORD=test ... -p 8080:8080 financials` — app starts, login works
3. `alembic upgrade head` — migrations apply against local Postgres
4. Open `/settings`, click "+ Connect New", complete Plaid Link for one institution — institution appears in list
5. Click "Sync now" — sync log shows a new entry, transactions appear on `/`
6. Filter by institution — only that institution's transactions shown
7. Click Disconnect — institution removed, its transactions cascade-deleted
8. Push to `main` — DO auto-deploys, Release Command runs migrations, app stays up
