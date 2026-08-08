# Dashboard spend chart + weekly budget: spend definition and boundary rules

**Date**: 2026-07-05
**Type**: decision
**Summary**: Dashboard spend chart + weekly $1000 budget tracker — spend = positive amount excluding transfer/loan-payment categories, weeks summed over full Sun–Sat boundaries, current-month default on a self-labeled section
**Context**: .minerva/work/010-dashboard-spend-and-budget

## Context

Work unit 010 added a spending section to the dashboard (`/`): a daily spend
bar chart plus a weekly budget tracker ($1000/week). The logic lives in the
pure module `app/spending.py` (`is_spend`, `daily_spend`, `weekly_budget`),
computed in `routes._spending_context` and rendered in `index.html`.

## Decisions

1. **Spend definition** — "spend" is a positive `amount` (money out; negatives
   are inflows) **excluding** Plaid `personal_finance_category` primaries with
   prefix `TRANSFER` or `LOAN_PAYMENTS`. Without this exclusion a credit-card
   payment (a checking outflow) double-counts against the same purchases it
   settles, and account transfers inflate the total — fatal for a budget.
   **Null/empty category is COUNTED as spend** (it can't be classified, and
   `category` is nullable / added by a later migration), so historical data
   without categories may over-count transfers. The exclusion set is
   provisional, mirroring the frank category stance in
   [[003-decision-subscriptions-cadence-only-detection]]. A separate
   spend-like aggregation already exists in `app/chat/tools.py`; this one is
   intentionally independent.

2. **Full Sun–Sat week summation across month boundaries** — the weekly
   tracker shows every Sun–Sat week that *overlaps* the selected month, and
   each week's `spent` sums the **whole** week even when some days fall outside
   the month. Both the DB query (`_spending_context` pads the fetch to
   `week_start(month_start)` … `week_start(last_day)+7`) and `weekly_budget`
   itself use the padded span. This prevents the edge weeks (which almost
   always straddle the boundary, since months rarely start on a Sunday) from
   silently undercounting against the $1000 budget. Weeks run Sun–Sat, matching
   `routes._group_by_week`.

3. **`is_current` / running-total semantics** — a week is flagged
   `is_current` (rendered with the "This week" highlight and running total)
   only when it is the week containing `today` **and** that week overlaps the
   displayed month. Viewing a past month therefore shows completed weeks with
   no misleading "running" badge.

4. **Current-month default on a self-labeled section** — the spending section
   defaults to the current month when no `?month=` is set, even though the
   transactions table keeps its existing all-time default. The mismatch is made
   unambiguous by giving the section its own explicit month header
   ("Spending · July 2026") rather than changing the table's default (which
   would be a broader, riskier behavior change). A malformed `?month=` falls
   back to the current month rather than 500-ing, matching the table's
   tolerance.

## Rendering

Dependency-free: a CSS flex bar chart (bar height ∝ day spend / month max) and
Bootstrap progress bars for the weekly tracker — no client charting library, so
all the real logic stays server-side and unit-tested (chosen over a Chart.js
CDN approach for exactly this reason).

## Known limitations (v1)

- Exclusion set (`TRANSFER`/`LOAN_PAYMENTS`) is provisional and not
  user-configurable; null-category outflows over-count.
- `$1000` weekly budget is a hardcoded constant.
- "Timeframe" selection is month-granularity only (reuses the existing month
  selector); no arbitrary date-range picker yet.

## Related

- [[003-decision-subscriptions-cadence-only-detection]] — see also
  the analogous "compute a view from stored transactions" pattern and category stance.
- [[006-decision-bills-payment-status-algorithm]] — see also
  sibling monthly-overlay view derived from transactions.
- [[004-pattern-seed-relative-dates-in-time-sensitive-tests]] — see also
  why `spending.py` takes the reference date as a parameter.
- [[009-decision-chart-click-window-filter]] — see also
- [[010-decision-budget-alert-notifier]] — see also
- [[016-decision-daily-digest-notifier]] — see also
