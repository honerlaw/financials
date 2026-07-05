## Goal

On the main dashboard (`/`), add two related spending views:

1. **Spend chart** — a graph of daily spend over the selected timeframe,
   defaulting to the current month, driven by the existing month selector
   (`?month=YYYY-MM`).
2. **Weekly budget tracker** — a running count of each Sun–Saturday week's
   spend against a **$1000/week budget**, with the current week's
   running total highlighted.

## Why

The dashboard shows transactions and per-account totals but gives no sense of
*spending pace* — is this month heavier than usual, and are we on track against
a weekly budget? A per-day spend graph plus a live weekly $1000 tracker answers
"how much have we spent, and are we over?" at a glance, grounded in real
transaction history.

## Status

Draft

## Approach

Approach A — server-side pure functions + dependency-free rendering (chosen over
a Chart.js CDN chart, which adds a client dependency and moves logic off the
tested path, and over a coarse unified weekly-bar chart, which loses daily
granularity).

**`app/spending.py`** — new module of pure functions taking the reference date
as a parameter (per the seed-relative-dates knowledge rule):

- `WEEKLY_BUDGET = 1000`.
- `is_spend(txn)` → `True` for a spending outflow. Spend = positive `amount`
  (money out; negatives are inflows), **excluding** transfer / loan-payment
  Plaid categories so credit-card payments and account transfers don't
  double-count against the budget. **Documented limitation:** `category` is
  nullable (added by a later migration); a transaction with `category is None`
  cannot be classified, so it is counted as spend — older transfers/CC-payments
  may inflate historical spend. Provisional, mirroring subscriptions.py's frank
  category note. (A third spend-like definition already lives in
  `app/chat/tools.py`; this one is intentionally separate and documented.)
- `week_start(d)` → the Sunday of `d`'s week (`d - (d.weekday()+1)%7`), matching
  `routes._group_by_week`.
- `daily_spend(transactions, start, end_exclusive)` → ordered
  `[(date, total_spend)]` for **every** day in `[start, end_exclusive)`, zero
  days filled, for the chart.
- `weekly_budget(transactions, month_start, month_end_exclusive, today,
  budget=WEEKLY_BUDGET)` → one dict per Sun–Sat week **overlapping** the month:
  `{week_start, week_end, label, spent, budget, remaining, pct, over,
  is_current}`. `spent` sums the **full** Sun–Sat week (see week-boundary note),
  so the $1000 comparison is apples-to-apples. `is_current` is `True` only for
  the week containing `today` **and** only when that week overlaps the month —
  so a past month shows completed weeks with no "running" highlight.

**`app/routes.py`** — small helper `_spending_context(institution_id,
chart_month, today)` keeps `index()` readable:

- `chart_month` = selected `?month=` or, when unset, the current month
  (`today.strftime('%Y-%m')`). The spending section thus **defaults to the
  current month** even though the transactions table keeps its existing
  all-time default — the section carries an explicit month header so the two
  scopes are self-labeled and unambiguous.
- **Week-boundary handling (load-bearing):** query transactions over a range
  *padded to full Sun–Sat week boundaries* covering the month —
  `week_start(month_start)` through `week_start(last_day)+7` — so edge weeks
  that straddle the month boundary are summed in full, not undercounted. The
  institution filter and `removed=False` are honored, matching the table.
- One extra unpaginated query over that padded range; feed it to both
  `daily_spend` (sliced to the month) and `weekly_budget`.

**`app/templates/index.html`** — new "Spending" section above the account cards:

- Section header naming the month it reflects (e.g. "Spending · July 2026").
- **Weekly budget tracker:** a card/row per overlapping week with a Bootstrap
  progress bar (green under budget, amber near, red over), `$spent / $1000`,
  and remaining; the current week highlighted with a "This week" badge and its
  running total.
- **Daily spend chart:** dependency-free CSS bar chart (flex divs, height ∝
  spend / max), one bar per day, `title` tooltip per day.

**`tests/test_spending.py`** — pure-function tests seeded with **relative**
dates (per [[004-pattern-seed-relative-dates-in-time-sensitive-tests]]):
`is_spend` sign + category exclusion + null-category counted; `daily_spend`
zero-fill and summation; `weekly_budget` per-week totals, over/under, current-
week flag, and full-week summation across a month boundary. Plus a route test
that `/` renders the spending section.

## Success criteria

1. `app/spending.py` exposes `is_spend`, `daily_spend`, `weekly_budget` as pure
   functions taking the reference date as a parameter (no hidden `date.today()`
   in the math). Spend = positive `amount` excluding transfer/loan-payment
   categories; null-category outflows counted (documented).
2. The dashboard `/` shows a daily spend chart over the selected timeframe,
   defaulting to the current month, changing when the month selector changes.
3. The dashboard shows a weekly budget tracker: each Sun–Sat week's spend vs
   $1000, with the current week's running total highlighted; edge weeks that
   cross the month boundary are summed over the **full** Sun–Sat week (not
   undercounted).
4. The institution filter is honored by the chart and tracker.
5. `is_current` is `True` only for the week containing `today` and only when it
   overlaps the displayed month (past months show no running highlight).
6. `pytest` passes (new `tests/test_spending.py` + the existing suite).
7. `/` renders without error for both the default (no `?month=`) and an
   explicit `?month=` load.

## Open Questions

- Exact spend-exclusion set (transfers + loan payments) is provisional; the
  user may want to refine which Plaid categories count toward the budget.
- "Select dates" is interpreted as month selection (the existing control); an
  arbitrary date-range picker is deferred to a follow-up.
- `$1000` weekly budget is a hardcoded constant; making it user-configurable is
  a follow-up.
