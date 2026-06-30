# Proposal: fix-bills-inactive-sort-test

**Date**: 2026-06-30
**Status**: Shipped (2026-06-30)

## Goal

Make `tests/test_bills.py::test_inactive_sorts_last` deterministic so it stops
failing as real calendar time advances.

## Why

`detect_bills` is a pure function that takes `today` as an argument, but the
test mixed two clocks: it seeded the "ELECTRIC" stream with **fixed** dates
(`monthly_bill(5, day=5)` → Jan–May 5 2026, last charge May 5) while passing the
**real** `date.today()` as `today`. Once real time drifted past mid-June 2026,
May 5 aged beyond the active boundary (`1.5 × 30 = 45` days), so the electric
stream flipped `unpaid → inactive`, `'unpaid'` dropped out of the result, and
`statuses.index('unpaid')` raised `ValueError: 'unpaid' is not in list`. This is
exactly the time-bomb described in knowledge
`004-pattern-seed-relative-dates-in-time-sensitive-tests`.

## Approach

In `test_inactive_sorts_last`, use the file's existing fixed `TODAY =
date(2026, 6, 13)` constant for both the inactive-stream seed reference and the
`detect_bills(...)` call, instead of `date.today()`. For a pure function that
takes the reference date as an argument, a fixed `today` + fixed seeds is fully
deterministic (knowledge `004`), and it matches how every other payment-status
test in the file already works. Also add explicit `'unpaid' in statuses` /
`'inactive' in statuses` assertions so a future regression fails with a clear
message instead of an opaque `ValueError`.

Rejected alternative: reseed the electric stream relative to `date.today()`.
The unpaid/paid/upcoming classification is calendar-day-of-month sensitive, so a
`today - 30*k` seed risks landing on `paid`/`upcoming` for some real dates —
fixed-today is the robust choice.

## Success criteria

- `pytest tests/test_bills.py::test_inactive_sorts_last` passes.
- The test contains no `date.today()` call (no real-clock dependency).
- Full suite (`pytest`) passes with 0 failures.

## Open Questions

- None.
