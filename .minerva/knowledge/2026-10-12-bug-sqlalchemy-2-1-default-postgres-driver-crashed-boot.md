# An unpinned SQLAlchemy 2.1 switched the Postgres driver to psycopg 3 and crashed the container at boot

**Date**: 2026-10-12
**Type**: bug
**Theme**: deployment
**Summary**: Unpinned SQLAlchemy 2.1 defaulted `postgresql://` to psycopg 3, absent from the image; boot crashed.
**Context**: .minerva/work/2026-10-12-pin-sqlalchemy-postgres-driver (see git history if the worktree has been cleaned up)

## Context

The App Platform deploy of `14645a8` (PR #51, a digest-SMS change) failed with
`DeployContainerExitNonZero` and was automatically rolled back. Nothing in that PR touched
the database layer. Production kept serving the previous build, and any further push to
`main` would have failed identically.

## Finding

`requirements.txt` never pinned SQLAlchemy — it arrived through `flask-sqlalchemy>=3.1.0` —
and the Dockerfile re-resolves every requirement on each build. The failing build resolved
**SQLAlchemy 2.1.4**, which changed the default DBAPI for a bare `postgresql://` URL from
psycopg2 to **psycopg (v3)**. The image installs only `psycopg2-binary`, so `db.init_app`
raised `ModuleNotFoundError: No module named 'psycopg'` while creating the engine (the DBAPI
is imported at engine creation, without connecting). That happens inside `create_app`, so
`flask db upgrade` in `entrypoint.sh` exited non-zero before gunicorn ever bound port 8080.

Fixed two ways, deliberately both: `SQLAlchemy>=2.0,<2.1` is pinned (restoring the
last-known-good line — the suite runs on SQLite and cannot vouch for Postgres behaviour
under 2.1, [[033-pattern-sqlite-tests-cannot-catch-postgres-transaction-aborts]]), and
`app/__init__.py:_database_url` rewrites bare `postgres://` / `postgresql://` to
`postgresql+psycopg2://`, so the driver no longer depends on SQLAlchemy's default at all.
`DATABASE_ADMIN_URL` (used for migrations) goes through the same `create_app` path.

## Implications

- **This app is psycopg2-only unless a URL names a driver.** Moving to SQLAlchemy 2.1 or
  psycopg 3 is its own change: lift the pin, swap `psycopg2-binary` for `psycopg[binary]`,
  and change the helper's target together.
- **The SQLite test suite cannot catch this class of failure.** 321 tests passed under
  SQLAlchemy 2.1.4 in a production-like venv; the crash is in driver selection for a
  Postgres URL, which no test exercised until `tests/test_app_config.py`. Under the 2.0 pin
  its URI assertion is the guard — the dialect assertion would pass without the fix.
- **Every other requirement still floats**, so the same failure is possible for any of
  them on any push; tracked as issue #52 (lockfile).
- **Diagnosing a failed deploy**: `doctl apps list-deployments <app>` shows the failed
  deployment and the automated-rollback row; `doctl apps logs <app> financials
  --deployment <id> --type deploy` carries the crash traceback and `--type build` the pip
  resolution (which is how the 2.1.4 resolve was found). A logged-in `GET /` is the
  post-deploy check — `/login` returns 200 on a rolled-back build too.

## Related

- [[033-pattern-sqlite-tests-cannot-catch-postgres-transaction-aborts]] — see also: why the fix pins rather than adopting 2.1 on the strength of a SQLite-only suite.
- [[011-decision-doppler-hybrid-config]] — see also: `DATABASE_URL` comes from the DigitalOcean binding, not Doppler, and reaches the app through `entrypoint.sh`.
- [[017-pattern-migration-chain-is-postgres-only]] — see also: another place where Postgres-specific behaviour is invisible to the SQLite suite.
