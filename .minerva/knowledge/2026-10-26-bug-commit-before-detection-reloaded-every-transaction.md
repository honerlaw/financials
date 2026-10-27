# /bills stayed at ~20 s after the merchant index shipped: a commit expired every row detection then read

**Date**: 2026-10-26
**Type**: bug
**Theme**: recurring-detection
**Summary**: Routes committed between loading and detecting, expiring ORM rows; detection re-SELECTed 7,500 transactions individually.
**Context**: .minerva/work/2026-10-26-bills-monthly-total (see git history if the worktree has been cleaned up)

## Context

Knowledge 029 moved merchant grouping to sync time precisely because `/bills` and
`/subscriptions` took ~20 s. On 2026-10-26 production still took 20–23 s for both
(the dashboard: 0.25 s), with clean syncs and a usable index. The O(n²) grouping it
removed was not the only cost — and nothing had measured the page after it shipped.

## Finding

Both routes did `groups, _ = groups_for_detection(); db.session.commit();
detect_*_from_groups(groups, ...)`. The commit exists to persist an index build
`groups_for_detection()` may have just done, but with Flask-SQLAlchemy's default
`expire_on_commit=True` it also expired every `Transaction` instance just loaded.
Detection's first attribute read on each row then lazily re-SELECTed it: **7,505
queries per page** on a 7,500-transaction Postgres reproduction. At ~2–3 ms per round
trip to the managed database that is the ~20 s observed.

Fixed twice over:

1. The commit moved to **after** detection (detection returns plain dicts).
2. `merchant_groups._detection_rows()` now selects only the 11 columns detection reads
   (`_DETECTION_COLUMNS`) as plain Core rows instead of ORM instances. Hydrating full
   instances — each decoding two JSON columns nothing reads — was most of what remained.
   Plain rows cannot lazy-load, so this class of N+1 is gone structurally.

Reproduction: `/bills` 7,505 queries / ~1.9 s locally → 5 queries / ~0.06 s.

## Implications

- **Detection is duck-typed over plain rows.** Reading any new attribute in
  `app/bills.py` or `app/subscriptions.py` requires adding its column to
  `_DETECTION_COLUMNS`; otherwise production raises `AttributeError` while the
  `FakeTxn` unit tests still pass. The route tests (`test_bills_page_*`) are what
  exercise real rows.
- `test_page_query_count_does_not_grow_with_transactions` pins the property both fixes
  protect: the same SELECT count for 20 and 200 transactions on a warm index. It failed
  on the pre-fix code (28 vs 208). SQLite expires and reloads like Postgres does, so
  unlike knowledge 033's class this one is catchable on the suite's backend.
- A performance fix is done when the **page** is re-timed, not the component it targets.

## Related
- [[029-decision-merchant-grouping-precomputed-at-sync]] — the earlier fix for the same 20 s symptom; this was the cost it left behind
- [[033-pattern-sqlite-tests-cannot-catch-postgres-transaction-aborts]] — contrast: this regression *is* visible on SQLite
- [[2026-10-26-decision-fixed-monthly-bills-total]] — shipped in the same unit
