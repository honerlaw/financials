# Tests exercising code that calls `date.today()` must seed dates relative to today

**Date**: 2026-06-07
**Type**: pattern
**Summary**: Any test exercising code that calls `date.today()` must seed fixtures relative to today (or freeze the clock) — fixed calendar dates drift across behavioral boundaries into delayed-fuse failures.
**Context**: .minerva/work/004-subscriptions-view (see git history if the worktree has been cleaned up)

## Context

The `/subscriptions` route calls `date.today()` to compute each stream's
active/inactive status (inactive when overdue by >1.5× its cadence). The
first draft of its route test seeded transactions on fixed calendar dates
(Mar/Apr/May 2026) and asserted the stream rendered as active.

## Finding

A fixed-date seed against `date.today()`-dependent logic is a time bomb: the
test passes today, then starts failing weeks later when real time drifts the
fixture across a behavioral boundary (here, the last charge falling more
than 45 days into the past, flipping the stream to inactive). Nothing in the
diff that eventually breaks the build will mention this test.

The fix is to seed fixtures relative to `date.today()`
(`today - timedelta(days=60)`, `today - timedelta(days=30)`, `today`), so
the fixture's distance from "now" — the thing the code under test actually
measures — is invariant. See `tests/test_subscriptions.py::_seed_recurring`.

Pure functions avoid the problem entirely by taking `today` as a parameter
(`detect_subscriptions(transactions, today)`), which is why only the route
tests — where `date.today()` is called inside the request — need this
pattern.

## Implications

- Any future route/view test whose code path calls `date.today()` (or
  `datetime.now`) must either seed relative dates or inject/freeze the
  clock. Fixed calendar dates are only safe for pure functions that take
  the reference date as an argument.
- When a previously-green test fails with no related diff, check for this
  pattern before bisecting.

## Related
- [[003-decision-subscriptions-cadence-only-detection]] — see also
- [[008-decision-dashboard-spend-and-weekly-budget]] — see also
- [[010-decision-budget-alert-notifier]] — see also
- [[012-pattern-fetch-content-type-session-detection]] — see also
