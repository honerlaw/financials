# Proposal: transactions-week-sections

**Date**: 2026-06-13
**Status**: Shipped (2026-06-13)

## Goal

Add week-based section headers to the transactions list, grouping rows by Sunday–Saturday week and displaying a divider row with the week date range between groups.

## Why

Flat date-ordered rows make it slow to visually parse "what did I spend this week" — week dividers provide a natural anchor for browsing spending patterns without any filter changes.

## Approach

- Add `_group_by_week(transactions)` helper in `app/routes.py`: compute the preceding Sunday for each transaction's date, bucket into `{week_start: [txns]}`, return a sorted list of `(label, txns)` where label is e.g. "Jun 8 – Jun 14, 2026".
- Pass `week_groups` to `index.html` alongside the existing `transactions` pagination object (pagination controls unchanged).
- In `index.html`, replace the flat `{% for txn in transactions.items %}` loop with an outer `{% for label, group in week_groups %}` loop, inserting a `<tr>` section header between groups, then an inner `{% for txn in group %}` loop.

## Success criteria

1. Week-label divider rows appear between transaction groups on the transactions page.
2. A transaction on any given day appears under the week whose Sunday ≤ transaction date ≤ Saturday (preceding Sunday boundary).
3. Existing pagination (50/page), institution filter, and month filter all still work.
4. Unit test covers `_group_by_week()` correctness including the Sunday-boundary case.

## Open Questions

None.
