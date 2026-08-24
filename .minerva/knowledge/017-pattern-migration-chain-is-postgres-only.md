# Verifying a migration without Postgres

**Date**: 2026-08-08
**Type**: pattern
**Summary**: The Alembic chain cannot be replayed on SQLite (00a2889ed2af issues Postgres GRANTs), so a new migration is verified in isolation — stamp the parent, hand-create the tables it touches, upgrade, downgrade.
**Context**: .minerva/work/016-daily-balance-digest

## Finding

`flask db upgrade` against a scratch SQLite file **cannot** replay this repo's
migration chain: `00a2889ed2af_grant_permissions_to_financials_admin.py` issues
`GRANT USAGE ON SCHEMA public …`, which SQLite rejects with
`OperationalError: near "GRANT": syntax error`. The chain halts there, several
revisions short of head.

This is easy to mistake for a problem with the migration under test. It is not —
and the test suite hides it, because `tests/conftest.py` builds its schema with
`db.create_all()` from the models, never through Alembic. **A migration can
therefore be wrong in a way no test catches.**

## The workaround

Exercise the new revision in isolation against SQLite:

1. Create a scratch SQLite DB and hand-create only the tables the revision
   touches (for a `drop_table`, the table must exist first).
2. `flask db stamp <parent_revision>` so Alembic believes everything earlier has
   already run.
3. `flask db upgrade` — only the new revision executes. Assert the resulting
   schema with `sqlite_master` / `pragma index_list`.
4. `flask db downgrade <parent_revision>` (note: `downgrade -1` is not valid
   flag syntax for the flask CLI) and assert the inverse.

Valid only for portable DDL — `create_table`, `drop_table`, plain column adds.
A revision using Postgres-specific types, `USING` casts, or concurrent index
builds still needs a real Postgres.

## Related

- [[016-decision-daily-digest-notifier]] — builds on
  the unit whose migration (`d5a1c9e37b48`) was verified this way.
- [[011-decision-doppler-hybrid-config]] — see also
  `DATABASE_ADMIN_URL`, the privileged URL the production `flask db upgrade` runs under.
- [[021-decision-plaid-vested-value-piggyback-on-sync]] — see also
