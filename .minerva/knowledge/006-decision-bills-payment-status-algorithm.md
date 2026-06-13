---
name: bills-payment-status-algorithm
description: Monthly payment status for bills uses median day-of-month from history + ±PAYMENT_WINDOW (6 days) window check against current-month transactions
metadata:
  type: decision
---

# Bills payment status: median day-of-month + ±6-day window

**Date**: 2026-06-13
**Type**: decision
**Context**: .minerva/work/006-bills-view

## Context

Work unit 006 added `app/bills.py` with a `_payment_status(txns, today)` function
that classifies each active recurring outflow as `paid`, `unpaid`, or `upcoming`
for the current calendar month.

## Algorithm

1. **Expected day-of-month** = `median(t.date.day for t in txns)` (integer floor
   for even-count lists). This gives the typical calendar day a bill lands on
   (e.g. if charges historically hit the 14th and 15th, expected day = 14).

2. **Expected date this month** = `date(today.year, today.month, expected_day)`,
   clamped to the last day of the month via `_safe_date()` (handles Feb 28/29,
   Apr 30, etc.).

3. **Status logic**:
   - `today < expected_date − PAYMENT_WINDOW` → `'upcoming'`
   - Any transaction in the stream with `date.year == today.year and
     date.month == today.month and abs(date − expected_date) ≤ PAYMENT_WINDOW`
     → `'paid'`
   - Otherwise → `'unpaid'`

`PAYMENT_WINDOW = 6` days was chosen to match the monthly cadence tolerance
already used in `CADENCES` (`('monthly', 30, 6)`) in `subscriptions.py`.

## Known limitations (v1)

- **Non-monthly cadences**: weekly/biweekly bills compute a synthetic
  `expected_day` from all historical `.day` values, which produces an
  arbitrary date and may incorrectly show `'unpaid'` even when the current
  week's charge was already made. This is a v1 limitation — the algorithm
  is designed for monthly outflows. Weekly/biweekly bills are detected and
  shown but their payment status is best-effort.

- **Upcoming window overlap**: from `expected_date − PAYMENT_WINDOW` to
  `expected_date`, if no matching transaction exists yet, the bill already
  shows `'unpaid'` rather than `'upcoming'` — so there is a 6-day lead-up
  where an unfulfilled bill shows red. This is intentional (early warning)
  but worth knowing for UX decisions.

## Related

- [[005-decision-bills-inactive-override]] — inactive streams bypass this
  algorithm entirely.
- [[003-decision-subscriptions-cadence-only-detection]] — source of
  `PAYMENT_WINDOW = 6` (monthly tolerance) and the `CADENCES` definition.
