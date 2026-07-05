# Followups — 012-weekly-budget-sms-alerts

## Enforce (or remove reliance on) the single-worker invariant

The budget-alert notifier prevents duplicate SMS with a module-level
`threading.Lock`, which is correct only under `gunicorn --workers 1`
(`entrypoint.sh`). That invariant is **not runtime-enforced** anywhere. If worker
count is ever raised (a platform autoscale override, an ops change for perf), the
in-process lock silently becomes a no-op across processes and cross-process
duplicate SMS become possible — the `BudgetAlert` unique constraint suppresses
the duplicate *row* but not the already-sent *text*.

Options for a future work unit:
- Fail loud at startup if the effective worker count > 1 (a broad, app-wide
  guard — the in-process APScheduler in `wsgi.py` already depends on single-worker
  too, so this protects more than just alerts).
- Move dedup to a Postgres advisory lock (`pg_advisory_xact_lock`) so correctness
  no longer depends on process count (needs a SQLite-test accommodation).

Severity is low as shipped (the invariant holds today and is documented in
`app/notifications.py` and [[budget-alert-notifier]]); this is hardening, not a
live bug.

_Source: 012 review triage (independent code-review finding #3), 2026-07-05._
