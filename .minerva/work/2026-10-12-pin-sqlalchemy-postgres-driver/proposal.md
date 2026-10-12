# Proposal: pin-sqlalchemy-postgres-driver

**Date**: 2026-10-12
**Status**: Draft

## Goal

Make the production container boot again: the App Platform deploy of `14645a8` (PR #51)
crashed at `create_app` with `ModuleNotFoundError: No module named 'psycopg'` and was
auto-rolled back. Pin SQLAlchemy to the 2.0 line and name the psycopg2 driver explicitly
in the database URL, so neither a dependency resolution nor a future default change can
pick a driver the image does not install.

## Why

Diagnosed this session (minerva:debug, Confirmed):
- `requirements.txt` does not pin SQLAlchemy — it arrives transitively through
  `flask-sqlalchemy>=3.1.0`, and every App Platform build re-resolves dependencies.
- The failing build installed `sqlalchemy-2.1.4` (build log). SQLAlchemy 2.1 changed the
  default DBAPI for a bare `postgresql://` URL from psycopg2 to psycopg (v3); reproduced
  locally: 2.1.4 → `psycopg`, 2.0.49 (local venv) → `psycopg2`.
- The image installs only `psycopg2-binary`, so `db.init_app` fails, `flask db upgrade` in
  `entrypoint.sh` exits non-zero, gunicorn never binds 8080, health checks fail.
- Production is serving the rolled-back pre-#51 build; any push to `main` fails the same way
  until this is fixed. PR #51's code is not involved (the crash precedes any app module
  import beyond `create_app`; the suite passes 321/321 on the production-resolved set,
  SQLAlchemy 2.1.4 included — on SQLite, so that is evidence about Python behaviour, not
  Postgres semantics, per knowledge 033). PR #51 added no migration, so the next deploy is
  the first time its code runs against production Postgres, but not a schema change.

## Approach

1. **Pin** `SQLAlchemy>=2.0,<2.1` in `requirements.txt`, with a comment naming the reason
   (2.1 changes the default PostgreSQL driver; the test suite runs on SQLite and cannot
   vouch for Postgres behaviour under 2.1) and noting that every other requirement still
   floats. This restores the last-known-good SQLAlchemy line. If `flask-sqlalchemy` ever
   requires 2.1, the build fails loudly at resolve time — acceptable. A deliberate move to
   SQLAlchemy 2.1 / psycopg 3 is a separate migration.
2. **Name the driver.** Replace the inline `postgres://` → `postgresql://` rewrite in
   `create_app` with a small pure helper, `_database_url(raw)`, that rewrites a bare
   `postgres://` **or** `postgresql://` scheme (prefix match, never a substring replace;
   the rest of the URL, including a `?sslmode=require` query string, is preserved) to
   `postgresql+psycopg2://`, and leaves any URL that already names a driver
   (`postgresql+…://`) or a non-Postgres URL (SQLite) untouched. Documented as: this app is
   psycopg2-only unless the URL names a driver. Scheme matching is case-sensitive on
   purpose: DigitalOcean's binding and `.env.example` both supply lowercase schemes, and an
   unrecognised scheme is passed through unchanged for SQLAlchemy to reject loudly. `DATABASE_ADMIN_URL` goes through the same path (`entrypoint.sh` exports it
   as `DATABASE_URL` for `flask db upgrade`, and `migrations/env.py` reuses the app's
   engine), so migrations get the same driver.
3. **Tests** (`tests/test_app_config.py`): the helper's rewrite table; and a
   version-independent test that `create_app` with a bare `postgresql://` URL sets
   `SQLALCHEMY_DATABASE_URI` to `postgresql+psycopg2://…` and its engine's dialect driver
   is `psycopg2` (no connection is made). Under the 2.0 pin the driver assertion would
   pass even without step 2, so the URI assertion is the in-repo regression guard; that
   the fix works under 2.1 is shown by a **one-off manual run** of the new test file in a
   scratch venv with SQLAlchemy 2.1.4 and `psycopg2-binary` (so a pass cannot be a missing
   driver), before merge, recorded in the scratchpad (failing
   on `main`'s `create_app`, passing on the branch).

### Candidate approaches considered

- **A (recommended) — pin + explicit driver.** Restores the known-good stack and makes the
  driver choice independent of SQLAlchemy's default.
- **B — explicit driver only, stay on SQLAlchemy 2.1.** Boots, and the SQLite suite passes
  on 2.1.4, but Postgres-specific 2.1 behaviour (knowledge 033: SQLite cannot catch
  Postgres transaction semantics) would be untested in production. Rejected: adopting a
  minor version upgrade should be a deliberate change, not a side effect of a hotfix.
- **C — pin only.** Minimal, but the next unpin or bump reproduces the crash. Dominated by A
  at the cost of one helper.
- **D — switch to psycopg v3** (`psycopg[binary]`). A driver migration in a hotfix; larger
  blast radius on the production connection path. Rejected.
- Out of scope: pinning every dependency / a lockfile. Worth considering separately — every
  other requirement is also `>=`.

## Success criteria

1. `requirements.txt` pins `SQLAlchemy>=2.0,<2.1`; a fresh `pip install -r requirements.txt`
   in a clean venv resolves SQLAlchemy 2.0.x.
2. `_database_url` maps `postgres://…` and `postgresql://…` to `postgresql+psycopg2://…`,
   preserving the remainder (a `postgresql://…/db?sslmode=require` row keeps its query
   string), and leaves `postgresql+psycopg2://…`, `postgresql+psycopg://…` and `sqlite:///…`
   unchanged (test).
3. `create_app` with `DATABASE_URL=postgresql://u:p@h/d` sets `SQLALCHEMY_DATABASE_URI`
   to `postgresql+psycopg2://u:p@h/d` and yields an engine whose dialect driver is
   `psycopg2` (test, in the repo's pinned environment). A one-off scratch-venv run with
   SQLAlchemy 2.1.4 shows the same test file failing against `main`'s `app/__init__.py`
   and passing against the branch's; the output is recorded in the scratchpad.
4. Full suite passes.
5. After merge, `doctl apps list-deployments` shows the deployment whose cause names the
   merge commit in phase `ACTIVE` with no later automated-rollback row, and a logged-in
   `GET https://financials.honerlaw.io/` (DB-backed account cards; password from Doppler
   `APP_PASSWORD`, config `prd`) returns 200. (A bare
   `/login` 200 would also pass on the rolled-back build, so it is not the check.)

## Open Questions

- None blocking. Every other requirement still floats (`>=`), so this failure mode remains
  possible for other packages; a lockfile / full pinning is a separate decision, recorded
  at promote.
