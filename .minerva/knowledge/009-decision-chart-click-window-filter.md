---
name: chart-click-window-filter
description: Clicking a dashboard chart week/day filters the transactions table via ?start/?end date-window params, which take precedence over ?month; the spending chart stays month-scoped
metadata:
  type: decision
---

# Chart-click date-window filter: precedence and scope

**Date**: 2026-07-05
**Type**: decision
**Context**: .minerva/work/011-chart-click-filters-transactions

## Context

Work unit 011 made the 010 spending charts interactive: clicking a week card or
a day bar filters the transactions table (and its infinite scroll) to that
window. Built on the existing URL-param + server-filter pattern used by
`?institution=` / `?month=`.

## Decisions

1. **Date window = `?start=YYYY-MM-DD` (inclusive) + `?end=YYYY-MM-DD`
   (exclusive).** A day click sets a 1-day window; a week click sets the 7-day
   Sun–Sat window. The JS helper `selectWindow(startISO, days)` computes `end`
   client-side with **local** date math (not `toISOString()`, which would roll
   back a day in negative-UTC zones), preserves the other params, and drops
   `page`.

2. **Window takes precedence over `?month=` for the table.**
   `routes._table_date_bounds(args)` returns the window when both bounds parse
   and `start < end`, otherwise falls back to `_month_bounds(month)`. Both
   `index()` and `transactions_json()` (infinite scroll) use it, so the table
   and its lazy-loaded pages stay in sync. The **account-totals strip** also
   uses these effective bounds, so it reflects the same window.

3. **The spending chart itself stays scoped to `?month=`** (default current
   month), independent of the window — it remains a stable picker the user can
   keep clicking. Re-scoping the chart to the window is deliberately *not* done
   (see followups).

4. **Malformed/partial `start`/`end` is ignored, never 500** — a missing or
   unparseable bound (or `start >= end`) falls back to the month filter, the
   same tolerance the month param already has.

5. **Clicking a spend bar filters to ALL transactions that day**, not only
   spend-classified ones ([[008-decision-dashboard-spend-and-weekly-budget]]
   defines "spend" narrowly, but the table is the full transactions view) —
   the least-surprising reading of "filter the transactions to that window".

## Related

- [[008-decision-dashboard-spend-and-weekly-budget]] — the spending chart /
  weekly-budget section these clicks drive from.
