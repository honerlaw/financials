# The daily digest reports this month's bills: a Bills/Other split, paid count, still due

**Date**: 2026-11-21
**Type**: decision
**Theme**: daily-digest
**Summary**: Digest adds month-to-date Bills/Other split, bills paid, cadence-aware still-due estimate and projected bill total.
**Context**: .minerva/work/2026-11-21-digest-bills-outlook (see git history if the worktree has been cleaned up)

## Context

The digest reported the week's spend against the $1,000 budget, four completed weeks, card
balances and yesterday's purchases, but could not tell fixed obligations from discretionary
spending. `/recurring` already knew the bills (detection, user rules, the fixed monthly total
of [[2026-10-26-decision-fixed-monthly-bills-total]]). The user asked for the text to show how
many bills are paid, an estimate for the month, and a "bills vs not bills" split, to see how
much is still to come before month end.

## Finding

1. **A month-to-date block sits between `Week of …` and `Last 4 weeks`:**
   `<Month> so far: $T` / `Bills $B · Other $O` / blank / `Bills: P of N paid` /
   `Still due: ~$D (k bills)` (or `none`) / `Bills this month: ~$B+D`. Whole dollars. `~`
   marks estimates. Rendered by `notifications.month_lines`, and both send paths get it
   through `_digest_parts`.
2. **Bills are exactly the bills `/recurring` counts** (`excluded_reason is None`), found by
   the same detection: `recurring_rules.load_rules` (moved out of `routes.py` so both share
   it), `groups_for_detection` and `detect_recurring_with_rules`. B is every positive charge
   of those bills dated (`Transaction.date`) in the month. That includes payments that are not
   purchases, such as rent by Zelle and loan payments. O is the month's `is_spend` total less
   the bill charges that are themselves `is_spend` (`MonthBills.paid_spend`). The parts are
   rounded half-up first, so the printed totals are sums of what is printed, and O is floored
   at $0. The weekly budget line and the Yesterday list are unchanged.
3. **Still due is projected per cadence** (`bills.month_outlook` / `_remaining_charges`), at
   each bill's `occurrence_amount`. That is the P75 single charge that `monthly_amount` is
   built from before the cadence factor. `monthly_amount` itself is unchanged.
   - **monthly** (rule-forced too): paid once any charge posted this calendar month. This is
     deliberately not `_payment_status`'s ±6-day window
     ([[006-decision-bills-payment-status-algorithm]]), so the text's paid count can differ
     from the page's badges on a drifting day.
   - **quarterly**: counted in calendar months, not `cadence_days`, because 91 nominal days
     would make a bill charged on the 1st due a month early. It is due in the third calendar
     month after its last charge, or later if overdue. Otherwise it is not part of the month.
   - **twice a month**: a biweekly stream with exactly two charges in each of at least 3 of
     the up-to-6 complete prior months is treated as two a month, less those already charged.
     Otherwise a bill paid on the 1st and 15th was projected a phantom third charge.
   - **weekly / biweekly**: charges projected every `cadence_days` from the last one that
     fall from today to the month's end. Missed past ones count as skipped. Today's still
     counts as due, because the text goes out at 7am.
4. **Detection failure never costs the digest.** `_bill_outlook` runs last. On any exception
   it logs, calls a **full `session.rollback()`**, not a savepoint, and the text prints
   `<Month> purchases so far: $X` + `Bills: unavailable today`. A dropped connection (the
   failure mode of [[2026-11-16-bug-stale-pooled-connection-skipped-the-daily-digest]])
   leaves the session unusable until it is rolled back, and the `DailyDigest` write after the
   send needs it. On success it commits any merchant-index warm-up `groups_for_detection` did.
   Nothing else is pending at that point, and everything already read is plain data.

## Implications

- **"Bills" means detected recurring, not obligations.** A regularly visited merchant (a
  weekly grocery run) counts as a bill until it is marked not recurring on `/recurring`.
  Fixing the classification there fixes the text.
- **[[022-decision-digest-four-week-spend-history]] decision 3 is narrowed.** The spend
  aggregates still come from one transaction query. The fetch now reaches back to the first of
  the month, which on the 30th/31st predates the history window. Bill detection is a second,
  unbounded read, the same one a `/recurring` page load makes. The one-query test now calls
  `_spend_totals` directly.
- **[[2026-11-08-decision-digest-lists-every-purchase]] decision 3 is amended.**
  `PURCHASE_LIST_MAX` stays 15. With 3 cards the cap alone still fits the worst case (1,328
  characters, all 15 listed). The pathological 8-long-named-cards case now relies on the
  `BODY_MAX` backstop (1,585 characters, 13 listed). Shrinking the cap would have cut
  ordinary busy days.
- **Accepted residuals.** A monthly bill drifting across a month boundary (paid Oct 31, next
  Dec 1) shows as due in November. A weekly stream that often skips sessions overstates still
  due. Today's weekly charge is due until it posts. On SQLite the rollback path is proven
  only by a spy on `session.rollback` ([[033-pattern-sqlite-tests-cannot-catch-postgres-transaction-aborts]]).
- **The A2P coupling moved again.** The three samples in
  `docs/twilio-a2p-campaign-resubmission.md` were regenerated from `digest_body` (one month's
  bills with several, one, then none still due), and the campaign description now lists the
  month split and bill status. If the campaign is filed, both must be re-submitted, because
  `main` deploys on push.

## Related

- [[2026-11-08-decision-digest-lists-every-purchase]] — amends decision 3: the backstop, not the cap alone, covers the 8-card worst case once the bills block is present.
- [[022-decision-digest-four-week-spend-history]] — narrows decision 3: one query for the spend aggregates; bill detection is a separate read.
- [[2026-10-26-decision-fixed-monthly-bills-total]] — builds on: the counted-bill set and the P75 occurrence estimate.
- [[006-decision-bills-payment-status-algorithm]] — diverges: the digest's monthly paid rule is "any charge this month", not the ±6-day window.
- [[2026-11-07-decision-user-rules-correct-recurring-detection]] — builds on: rule streams are counted bills, rule-forced monthly ones projected as monthly.
- [[2026-11-16-bug-stale-pooled-connection-skipped-the-daily-digest]] — see also: why a failed bill outlook does a full rollback.
- [[2026-10-12-decision-digest-credit-cards-and-yesterday]] — see also: the rest of the message, unchanged.
