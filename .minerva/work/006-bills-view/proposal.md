## Goal

Add a `/bills` page that detects recurring outflow streams (bills) and shows
each bill's monthly paid/unpaid/upcoming status — so the user can see at a
glance which obligations have been met this month and which are overdue.

## Why

The subscriptions page surfaces what's recurring but doesn't help the user
track whether bills have actually been paid this month. A dedicated bills view
surfaces unpaid obligations before due dates are missed, grounded in real
transaction history rather than manual entry.

## Status

Shipped (2026-06-13)

## Approach

`app/bills.py` — new module with `detect_bills(transactions, today)`. Imports
`_group_transactions` and `_build_stream` (and related helpers) from
`subscriptions.py` as package-internal symbols. Runs the same cadence-based
detection, filters to outflows only (`is_inflow == False`), then adds monthly
payment status by:

1. Computing `expected_day_of_month` = median `.day` across all historical
   transaction dates for that stream.
2. Computing `expected_date_this_month` = `date(today.year, today.month,
   expected_day)`, clamped to the last day of the month.
3. Checking if any transaction in the stream falls within `±PAYMENT_WINDOW`
   days (6) of that expected date in the current calendar month.
4. Returning status: `'upcoming'` (expected date not yet reached),
   `'paid'` (matching transaction found), or `'unpaid'` (date passed, no
   matching transaction).

`app/routes.py` — add `/bills` route mirroring `/subscriptions`.

`app/templates/bills.html` — table with columns: Merchant, Cadence, Typical
amount, Expected date, Status (Paid / Unpaid / Upcoming), Last charge, Charges.

`app/templates/base.html` — add "Bills" nav link alongside "Subscriptions".

`tests/test_bills.py` — pure-function tests covering detection, outflow
filter, and all three payment status paths.

## Success criteria

1. `detect_bills()` only returns streams where `is_inflow == False` (positive
   median amount = money leaving).
2. A bill with a matching transaction within `±6` days of the expected
   day-of-month shows `payment_status == 'paid'`.
3. A bill past its expected date this month with no matching transaction shows
   `payment_status == 'unpaid'`.
4. A bill whose expected date this month hasn't arrived yet shows
   `payment_status == 'upcoming'`.
5. `pytest tests/test_bills.py` passes with no failures.
6. `/bills` renders without error; nav link present in `base.html`.

## Open Questions

- Should weekly/biweekly bills show one aggregated status or per-occurrence?
  (Current design: checks for any matching payment within the expected window —
  for biweekly, this means the first occurrence window; acceptable for v1.)
- Should quarterly/annual bills show "not due this month" rather than
  'upcoming'? (Current design: always computes expected day from median, so a
  quarterly bill will show 'upcoming' for two months before its quarter. Low
  priority for v1.)
