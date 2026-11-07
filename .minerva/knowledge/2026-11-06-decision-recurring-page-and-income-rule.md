# /recurring replaces /bills and /subscriptions; recurring income counts only with INCOME-category evidence, at P25

**Date**: 2026-11-06
**Type**: decision
**Theme**: recurring-detection
**Summary**: /recurring merges bills and subscriptions; income needs INCOME-category majority, estimated at P25.
**Context**: .minerva/work/2026-11-06-recurring-page (see git history if the worktree has been cleaned up)

## Context

The user wanted one place to see their relatively-fixed monthly expenses. `/subscriptions`
turned out to be `/bills` plus inflow streams, so the two pages split one view. In
production 53 of ~71 recurring expense streams were not counted toward the total (39
inactive, 14 annual), burying the counted ones. The user had just linked the account their
biweekly paycheck lands in, which made a recurring-income figure worth showing.

## Finding

1. **One page.** `/recurring` (`routes.recurring`, `templates/recurring.html`) shows three
   headlines: recurring expenses (the unchanged `fixed_monthly_total`, P75), recurring
   income (P25) and "left after recurring", which is hidden unless at least one income
   stream is counted. Below them sit the counted expenses (largest monthly amount first, with
   paid/upcoming/unpaid status), the uncounted expenses collapsed into one `<details>` per
   reason, and the income table. `/bills` and `/subscriptions` **302**-redirect to it. A
   browser caches a 301 indefinitely, so a rollback would strand bookmarks.
2. **One detection pass.** `bills.detect_recurring_from_groups(groups, today)` builds each
   group's stream once and returns `(bills, income)`. `detect_bills_from_groups` is now a
   wrapper. `detect_subscriptions*` have no production caller and remain the detector's
   tested reference implementation.
3. **Income estimate mirrors expenses with the sign and percentile flipped.** An occurrence
   is the absolute value of one date's *negative* amounts summed; positive rows are ignored.
   It uses the same exclusive-far-end 365-day window anchored on the latest deposit. The
   result is P25 × `MONTHLY_FACTOR`, and the total sums the rounded rows.
4. **Income needs positive evidence; expenses do not.** An income stream counts only when it
   is active, has a sub-annual cadence, and a *strict majority of its categorized rows* have
   a primary category starting `INCOME`. A wholly uncategorized stream is **not** income. The
   expense side's transfer rule is the opposite: an uncategorized stream counts as a bill.
   The asymmetry follows the direction of the error. Over-counting a bill errs safe.
   Over-counting income overstates what is left over. Transfers in, card-payment credits,
   refunds and reimbursements are listed as "not income".
5. **Uncounted expense rows carry no paid/unpaid badge.** This extends knowledge 005's logic
   from lapsed streams to annual and transfer rows, so an active card autopay row no longer
   shows "Unpaid". The dashboard account cards already flag overdue card payments from Plaid
   liabilities. A reason with no heading in `_EXCLUDED_GROUPS` still renders as its own group,
   so no uncounted bill can silently drop off the page.

## Implications

- A paycheck that Plaid does not categorize as `INCOME` is listed but not counted. A manual
  income override is the fallback, and none exists yet.
- The cadence buckets have no semi-monthly bucket, so pay on the 1st and 15th would be read
  as biweekly and overstated by ~8% (26/12 vs 24/12). The user's pay is biweekly.
- Mixed-sign merchant groups land wholly on one side by the detector's unchanged
  `is_inflow` (signed median < 0).
- The query-count regression test (`test_page_query_count_does_not_grow_with_transactions`)
  now guards `/recurring`. The `test_bills_page_*` route tests named in the 2026-10-26 entries
  became `test_recurring_page_*`.

## Related
- [[2026-10-26-decision-fixed-monthly-bills-total]] — the expense total this page headlines, unchanged; the page it describes as /bills is now /recurring
- [[2026-10-26-bug-commit-before-detection-reloaded-every-transaction]] — /recurring keeps commit-after-detection; its query-count guard moved to /recurring
- [[005-decision-bills-inactive-override]] — extended: no paid/unpaid badge on any uncounted row
- [[003-decision-subscriptions-cadence-only-detection]] — every recurring stream stays listed; detection unchanged
- [[008-decision-dashboard-spend-and-weekly-budget]] — shares the card-payment/transfer exclusion rationale
