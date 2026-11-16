# Proposal: 2026-11-16-reconnect-stale-db-connections

**Date**: 2026-11-16
**Status**: Draft

## Goal

The user's request: "fix it", after diagnosing why the daily digest text did not reach either recipient on the morning of 2026-11-16.

Make the 7am scheduled job (sync, then daily digest) survive a pooled Postgres connection that the server closed while it sat idle. When the job checks out a connection that has gone stale, it gets a fresh one instead of an error, so the sync and the digest both run.

Out of scope: a connection that drops in the middle of a transaction the job already holds (for example during a Plaid HTTP call inside `_sync_institution`). That case has not been observed. Pre-ping only acts at checkout.

## Why

Production runtime logs show the job's first query, `Institution.query.filter_by(status='active').all()` at `app/sync.py:39`, raising `psycopg2.OperationalError` on two mornings:

- 2026-11-13: "SSL connection has been closed unexpectedly".
- 2026-11-16: "SSL SYSCALL error: EOF detected".

Because the sync raised, `run_daily_sync` (`app/sync.py:31`) never reached `_send_daily_digest_safe()`. No digest was texted on either day, and `/settings` shows no SyncLog rows for those dates. The container had been up since the 2026-11-08 deploy, so this was not a deploy or restart.

`create_app` (`app/__init__.py`) sets no `SQLALCHEMY_ENGINE_OPTIONS`, so `pool_pre_ping` is off. The pool hands the 7am job a connection that last served a request the day before. After a disconnect error SQLAlchemy invalidates the pool, which is why the mornings in between worked.

## Approach

In `create_app`, add a default `SQLALCHEMY_ENGINE_OPTIONS={'pool_pre_ping': True, 'pool_recycle': 1800}` inside the existing `app.config.update(...)` block. The `config` override argument can still replace it; it replaces the whole dict, not single keys.

- **Pre-ping** pings each connection when it is checked out. On a disconnect error it discards that connection and opens a fresh one.
- **`pool_recycle`** replaces any connection older than 30 minutes at checkout. This is defence in depth, and the value is not load-bearing.

Alternatives considered:

- **(B) Send the digest even when the sync raises.** This complements A rather than being wrong. It would cover failures A does not, such as a non-DB crash constructing `PlaidClient`. As written, though, it would text balances from a failed sync without labelling them, which is in tension with knowledge 016 decision 5. It also addresses no observed failure. Deferred.
- **(C) Retry the job once on `OperationalError`.** This is redundant with pre-ping for the observed failure. A retry around a partially committed sync also needs rollback care (knowledge 033).

## Success criteria

1. An app built by `create_app` carries `SQLALCHEMY_ENGINE_OPTIONS` with `pool_pre_ping=True` and `pool_recycle=1800`, asserted by a test in `tests/test_app_config.py`.
2. A test in `tests/test_app_config.py` runs on a file-backed SQLite database (`tmp_path`, not `:memory:`). It closes a pooled connection's underlying DBAPI connection behind the pool's back, then runs a query through `db.session`, and the query succeeds. With pre-ping disabled the same test fails. That was checked once during work and recorded in the scratchpad.
3. `uv run pytest` passes in full.
4. A knowledge entry records the bug, its cause, the fix, and its limits: a SQLite simulation stands in for the Postgres SSL EOF, and only checkout-time staleness is covered.

## Open Questions

- Why the server drops the idle connection is unknown: an idle timeout or managed-database maintenance. The fix does not depend on it. The real confirmation is the next 7am runs.
