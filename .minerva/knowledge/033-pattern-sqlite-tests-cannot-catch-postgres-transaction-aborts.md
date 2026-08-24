# The SQLite test backend cannot catch Postgres aborted-transaction bugs

**Date**: 2026-08-24
**Type**: pattern
**Summary**: A missing savepoint around a best-effort write is invisible to this suite — SQLite keeps the session usable after a failed statement where Postgres aborts the whole transaction, so the test passes with and without the fix.

**Context**: .minerva/work/2026-08-24-merchant-group-index

## Context

`tests/conftest.py` runs every test against `sqlite:///:memory:`; production is
Postgres. That difference is normally benign and already known to hide migration
defects ([[017-pattern-migration-chain-is-postgres-only]]). It also hides a class
of *runtime* defect.

The merchant-index update was added as a best-effort step at the tail of
`_sync_institution`, and as a build-on-demand step in the page path, each wrapped
in a bare `try/except` that logged and carried on.

## Finding

On Postgres, a statement that fails inside an open transaction leaves that
transaction **aborted**: every subsequent statement on the connection raises
until someone rolls back. A bare `except` that then keeps using the session is
therefore not error handling — it is a second, worse failure:

- in the page path, the fallback's own query would raise, turning a slow page
  into a broken one — the exact outcome the fallback existed to prevent;
- in the sync path, the closing `db.session.commit()` would raise and escape,
  discarding the transactions already upserted for that institution, losing the
  SyncLog row, and killing the remaining institutions in the loop. This is the
  same failure `_create_account_if_missing` documents and solves with a savepoint.

**SQLite does not reproduce any of it.** Verified directly: removing the
`db.session.begin_nested()` and re-running the test that forces a genuine failing
statement still passes. The test documents the contract; it cannot enforce it.

## Implications

- **Wrap any best-effort DB step in `db.session.begin_nested()`, not a bare
  `try/except`.** The savepoint is what makes "log it and carry on" true on
  Postgres. `_create_account_if_missing` in `app/sync.py` is the reference
  implementation.
- Treat "the tests pass" as no evidence at all for transaction-abort behaviour.
  Correctness here is established by inspection and precedent, and the test's
  value is documenting the intent for the next reader.
- The same blind spot applies to anything else Postgres enforces and SQLite does
  not: deferred constraints, `SELECT FOR UPDATE`, and isolation-level behaviour.

## Related

- [[017-pattern-migration-chain-is-postgres-only]] — the same SQLite-vs-Postgres gap, for migrations rather than runtime
- [[029-decision-merchant-grouping-precomputed-at-sync]] — the work that surfaced it
