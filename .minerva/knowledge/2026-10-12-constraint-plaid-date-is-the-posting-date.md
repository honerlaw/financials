# Plaid's `date` is the posting date for posted transactions — key per-day reports on `authorized_date`

**Date**: 2026-10-12
**Type**: constraint
**Theme**: daily-digest
**Summary**: `Transaction.date` is Plaid's posting date once posted; per-day reports must key on `authorized_date or date`.
**Context**: .minerva/work/2026-10-12-digest-card-balances-and-yesterday (see git history if the worktree has been cleaned up)

## Context

The digest's first Yesterday section selected rows by `Transaction.date == yesterday`,
and the proposal claimed that including pending rows could never count a purchase twice
because sync flags a pending row `removed` when its posted replacement arrives. An
independent code review found the claim held only within one digest.

## Finding

`app/sync.py` stores Plaid's `date` in `Transaction.date` and Plaid's `authorized_date`
in `Transaction.authorized_date` (nullable). For a **pending** transaction `date` is the
day it happened; for a **posted** one it is the day it **posted**, which can trail the
purchase by days. So a purchase made Friday is pending (dated Fri) in Saturday's data,
and once it posts Monday the pending row is flagged `removed` and a new row arrives dated
Mon. Any report keyed on `date` per day shows it under Friday, then again under Monday.
A purchase with no pending stage is labelled with its posting day.

`spending.purchase_date(txn)` = `authorized_date or date` is the purchase day. Plaid
gives the pending and posted rows the same `authorized_date` in the normal case, which
is what makes a per-day report keyed on it show a purchase once.

## Implications

- **Per-day reporting keys on `purchase_date`; weekly totals key on `date`.** The week
  buckets (budget line, four-week history, dashboard weekly tracker) were deliberately
  left on `date`: there the cost is a purchase landing in an adjacent week, not a
  duplicate. The two keys can disagree about which week a purchase belongs to.
- **`authorized_date <= date` is observed behaviour, not a documented guarantee.** The
  digest's single fetch relies on it (a row purchased yesterday has `date` of yesterday
  or today, inside the window).
- **Residuals remain**: a posted row Plaid sends without `authorized_date` falls back to
  `date`, and one whose `authorized_date` differs from its pending row's is keyed
  differently — either can still appear twice. A purchase first seen after its day has
  passed is never in that day's report. Deduping on `pending_transaction_id` or a
  "reported" record would close the duplicate cases; neither exists.
- The dashboard's daily spend chart (`spending.daily_spend`) still buckets by `date`, so
  a bar there is "posted that day", not "bought that day".

## Related

- [[2026-10-12-decision-digest-credit-cards-and-yesterday]] — see also: the Yesterday section this constraint shaped.
- [[008-decision-dashboard-spend-and-weekly-budget]] — see also: the `date`-keyed weekly buckets and spend definition left unchanged.
