# A stale pooled Postgres connection crashed the 7am job and skipped the daily digest

**Date**: 2026-11-16
**Type**: bug
**Theme**: daily-digest
**Summary**: The engine had no `pool_pre_ping`, so the 7am job's first query failed on a dead idle connection; now enabled.
**Context**: .minerva/work/2026-11-16-reconnect-stale-db-connections (see git history if the worktree has been cleaned up)

## Context

The daily digest SMS reached neither recipient on 2026-11-13 or 2026-11-16, and `/settings`
showed no SyncLog rows for either date. The container had been up since the 2026-11-08 deploy,
so no restart or deploy explains the miss. That rules out the "no catch-up" limitation of
[[016-decision-daily-digest-notifier]].

## Finding

1. **The job's first query hit a connection the server had closed.** `doctl apps logs … --type
   run` showed APScheduler's `raised an exception` traceback at exactly 12:00:00 UTC (07:00 ET)
   on both days. It came from `Institution.query.filter_by(status='active').all()` in
   `sync_all_institutions`, with `psycopg2.OperationalError`: "SSL connection has been closed
   unexpectedly" on the 13th and "SSL SYSCALL error: EOF detected" on the 16th. So, contrary to
   the reference memory's "nearly useless", the run logs do carry the scheduler's job
   tracebacks.
2. **Nothing checked the connection before handing it out.** `create_app` set no
   `SQLALCHEMY_ENGINE_OPTIONS`. Under `gunicorn --workers 1` the pool's connection can sit idle
   from an evening page view until 7am, and the server dropped it in between. The cause of the
   drop, an idle timeout or managed-database maintenance, is still unknown. The fix does not
   depend on it.
3. **One failed query skips the whole morning.** `run_daily_sync` syncs, then texts. The sync
   is not wrapped, so its exception escaped the job before `_send_daily_digest_safe` ran.
4. **It recovered by itself the next day.** SQLAlchemy invalidates the pool on a recognised
   disconnect error, so the following morning got a fresh connection. That is why the misses
   were intermittent rather than daily.

## Fix

`create_app` now defaults `SQLALCHEMY_ENGINE_OPTIONS={'pool_pre_ping': True, 'pool_recycle':
1800}`. Pre-ping pings each connection at checkout and replaces a dead one. Recycle retires
connections older than 30 minutes. A `config` override replaces the whole dict. A test in
`tests/test_app_config.py` closes a pooled SQLite connection behind the pool's back and shows
the next `db.session` query succeeds on the shipped defaults and fails without pre-ping.

## Limits

- **The proof is a SQLite stand-in.** That psycopg2 classifies "SSL SYSCALL error: EOF
  detected" as a disconnect was confirmed only by reading SQLAlchemy 2.0.54's `is_disconnect`
  list, not by a Postgres test ([[033-pattern-sqlite-tests-cannot-catch-postgres-transaction-aborts]],
  [[034-pattern-only-the-call-site-is-authoritative-for-runtime-behaviour]]). The real
  confirmation is the following 7am runs, so check `/settings` for a daily SyncLog row.
- **Only checkout is covered.** A connection that dies mid-transaction, for example during a
  Plaid HTTP call inside `_sync_institution`, still raises. That case has not been observed.
- **Sending the digest despite a failed sync was deferred, not rejected.** It would cover non-DB
  sync crashes as well, but it needs a staleness label on the balances to respect 016 decision 5.

## Related

- [[016-decision-daily-digest-notifier]] — see also: the job's sync-then-text order, which is why one bad query costs the text.
- [[2026-10-12-bug-sqlalchemy-2-1-default-postgres-driver-crashed-boot]] — see also: the other `create_app` engine fix, and the `doctl apps logs` route used again here.
- [[033-pattern-sqlite-tests-cannot-catch-postgres-transaction-aborts]] — builds on: why the SQLite proof is labelled a stand-in.
