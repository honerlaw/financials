# Proposal: recurring-page

**Date**: 2026-11-06
**Status**: Draft

## Goal

One `/recurring` page that shows the user's relatively-fixed monthly money in and out,
replacing `/bills` and `/subscriptions`.

- **Headline.** "Recurring expenses $X / month" (noted as the 75th percentile of the last
  year), "Recurring income $Y / month" (noted as the 25th percentile of the last year — the
  low end), and "Left after recurring $Y − X", shown only when at least one income stream is
  counted. A status summary line over the counted expenses keeps the old `/bills` header:
  "n unpaid · n upcoming · n paid this month".
- **Counted expenses.** The rows behind $X, largest monthly amount first — a deliberate
  change from `/bills`' unpaid-first order; the summary line and per-row status badge keep
  "what is unpaid" visible. Columns: merchant, cadence, typical amount, per month, expected
  this month, last charge, accounts, paid/upcoming/unpaid status. The rows sum exactly to
  the headline.
- **Not counted.** One closed-by-default `<details>` per reason — Annual (n), Transfers (n),
  Inactive (n) — each row with its monthly equivalent. These rows carry **no** paid/unpaid
  badge, so an uncounted stream never raises a false "Unpaid" alarm (knowledge 005).
- **Recurring income.** Source, cadence, typical amount, per month, last deposit, next
  expected, accounts. Counted rows sum exactly to the income headline; uncounted rows are
  dimmed (`is-lapsed`) with their reason. Amounts use `text-success`.
- **Routing.** `/bills` and `/subscriptions` 302-redirect to `/recurring` (temporary, so a
  rollback leaves no browser-cached redirect), behind `@login_required` like every page. The
  nav has one "Recurring" link. The `/subscriptions` route and both old templates
  (`bills.html`, `subscriptions.html`) are removed.

## Why

The user wants to see their total "monthly" expenses that are relatively fixed, and said
bills and subscriptions "don't really help me understand the full picture". The two pages
fragment one view without adding information: `/subscriptions` is `/bills` plus inflow
streams. Production `/bills` (read 2026-11-06) lists ~71 recurring expense streams, of
which 53 are not counted (39 inactive, 14 annual), burying the counted list among rows that
do not affect the total.

Production detects only two recurring inflows today (savings interest and a lapsed biweekly
deposit) because the account the user's biweekly paycheck lands in was not linked. The user
has just linked it, and linking requests 730 days of history (`app/plaid_client.py:61`), so
a recurring income figure becomes meaningful once the backfill lands. The user chose: a new
`/recurring` page over extending `/bills`; income vs. expenses; counted/not-counted split;
not-counted collapsed and grouped by reason; income at the 25th percentile.

## Approach

- **Expense side unchanged.** `bills.fixed_monthly_total` and every expense rule in
  knowledge `2026-10-26-decision-fixed-monthly-bills-total` stand as they are.
- **One detection pass.** A new `detect_recurring_from_groups(groups, today)` in
  `app/bills.py` returns `(bills, income)`, calling `_build_stream` once per group: outflow
  streams get the existing bill fields, inflow streams (`is_inflow`) get income fields.
  `detect_bills_from_groups` stays, as a thin wrapper, for the parity tests.
- **Income estimate.** An occurrence is one date, its amount the absolute value of that
  date's **negative** amounts summed (positive rows ignored; no occurrences → `0.00`). Only
  dates `d > last deposit − 365 days` count — the same exclusive-far-end window as expenses,
  so a biweekly stream contributes 26 deposits, not 27. The monthly figure is the 25th
  percentile (existing `_percentile`) × `MONTHLY_FACTOR`, rounded to cents.
  `monthly_income_total(income) -> (total, count)` sums the rounded counted rows, the same
  pattern as `fixed_monthly_total`.
- **Income counted** = active, cadence weekly/biweekly/monthly/quarterly, and
  **income-categorized**: a strict majority of the stream's categorized rows have a primary
  `category` starting `INCOME` (Plaid `INCOME_WAGES`, `INCOME_INTEREST_EARNED`, …).
  Uncategorized rows abstain, and a wholly uncategorized stream is **not** counted. The
  excluded reason is the first of `inactive`, `annual`, `not income`. This is deliberately
  stricter than the expense side's transfer rule: an error on income is optimistic — it
  overstates what is left over — so income needs positive category evidence. Transfers in,
  card-payment credits, refunds, reimbursements and cashback all land under "not income",
  still listed with their reason.
- **Typical amount** column = `abs(stream['amount'])`, the stream's signed median over all
  rows — the source expense rows already use. Mixed-sign groups land wholly on one side via
  the detector's unchanged `is_inflow` (median < 0).
- **Route.** `routes.recurring()` replaces both routes: `groups_for_detection()` →
  `detect_recurring_from_groups` → `db.session.commit()` **after** detection (knowledge
  `2026-10-26-bug-commit-before-detection-reloaded-every-transaction`), account labels
  resolved once across both lists.
- **Tests migrated.** The query-count regression test in `tests/test_merchant_groups.py`
  (parametrized over `/bills`, `/subscriptions`) is repointed to `/recurring`. Route tests
  in `tests/test_bills.py` and `tests/test_subscriptions.py` move to `/recurring` (porting
  the not-counted reason, count and "/ month" total assertions) or become redirect
  assertions. Fixtures use synthetic merchant names only — the repo is public.
- **References.** Docstrings and comments naming the old URLs are updated
  (`merchant_groups.py`, `models.py`, `sync.py`). `app/chat/tools.py` names concepts, not
  URLs, and is left alone. The `detect_subscriptions*` functions stay: they remain the
  detector's tested reference implementation even with no route calling them.
- Income "next expected" renders `next_date` as-is; an active stream is at most 1.5× its
  cadence late, so a past date is visible and honest.
- **Out of scope:** counting annual bills, chat, the SMS digest, a semi-monthly cadence (the
  user confirmed biweekly pay), and a manual income override.

## Success criteria

- Unit tests cover the income estimate — 25th percentile, per-date summing, positive amounts
  ignored, the 365-day exclusive-far-end window (26 biweekly deposits, not 27), the 26/12
  biweekly factor — and income counting: inactive, annual, and not-income (`TRANSFER_IN`,
  card-payment credit, a wholly uncategorized inflow stream) are excluded; an
  `INCOME_WAGES` stream is counted.
- Route tests: `/recurring` renders the three figures; the expense headline equals
  `fixed_monthly_total` for the same data; counted expense rows and counted income rows each
  sum to their headline; a biweekly `INCOME_WAGES` stream renders its 26/12 monthly figure
  through the page; "Left after recurring" is absent when no income stream is counted;
  not-counted expense rows carry no Unpaid badge; `/bills` and `/subscriptions` return 302 to
  `/recurring` when logged in and redirect to login when not; the nav has a single Recurring
  link and no Bills/Subscriptions link.
- The query-count regression test covers `/recurring` and passes.
- `uv run pytest` passes.
- After deploy, production `/recurring` returns 200 within a few seconds.

## Open Questions

- Whether the paycheck appears depends on Plaid finishing the new account's backfill and on
  its rows carrying an `INCOME` category. Verify on production `/recurring` after deploy; a
  paycheck missing despite its history being present is a separate bug, and a manual income
  override is the fallback if Plaid does not categorize it.
