# The digest drops its four-week history and names the dates behind every month figure

**Date**: 2026-11-21
**Type**: decision
**Theme**: daily-digest
**Summary**: Digest's `Last 4 weeks` block removed; month lines read `Spent Nov 1–21`, `Bills Nov 1–30`, `Still due by Nov 30`, all bounded at today.
**Context**: .minerva/work/2026-11-21-digest-dated-bills-drop-history (see git history if the worktree has been cleaned up)

## Context

The month block added the same day ([[2026-11-21-decision-digest-reports-the-months-bills]])
used relative labels: `November so far`, `Still due`, `Bills this month`. The reader had to
work out which dates each figure covered. The user also found the four-week history
([[022-decision-digest-four-week-spend-history]]) not worth its lines. They asked to remove
it and to "denote the explicit start / end date of the time period its looking at".

## Finding

1. **The `Last 4 weeks` block is gone.** `HISTORY_WEEKS`, `history_line` and
   `spending.recent_week_spend` were deleted, and `digest_body` no longer takes `history`.
   The running week stays in the budget line and `Week of …`.
2. **Each month line names its period** (`notifications._period`, a same-month range with
   the week labels' unspaced en dash, collapsing to a single date):
   `Spent Nov 1–21: $T` / `Bills $B · Other $O` / blank / `Bills Nov 1–30: P of N paid` /
   `Still due by Nov 30: ~$D (k bills)` (or `none`) / `Bills total Nov 1–30: ~$B+D`.
   Variants: `Bills Nov 1–30: none detected`; on detection failure
   `Purchases Nov 1–21: $X` + `Bills: unavailable today`. On the 1st: `Spent Nov 1`.
3. **"Still due" states only the end date.** `_remaining_charges` enforces a start of today
   only for weekly/biweekly bills. An unpaid monthly bill whose usual day has passed, an
   overdue quarterly bill or a missed twice-a-month charge are still due. A `Nov 21–30`
   label would misstate them.
4. **"Through today" is enforced, not nominal.** `spending.month_spend` sums rows dated
   from the 1st through today (previously any date in the month), and `bills.month_outlook`
   ignores charges dated after today for both the paid total and the paid/due decision. The
   two stay on the same span, so Bills + Other still adds up.
5. **The single spend fetch starts at `min(week_start, month_start, yesterday)`**, still one
   query. `yesterday` is needed on Sundays. It is a sufficient floor for the
   purchase-date-keyed Yesterday section because Plaid's `date` never precedes
   `authorized_date` ([[2026-10-12-constraint-plaid-date-is-the-posting-date]]).
6. **With the history gone, the cap alone fits the worst case again.** Eight long-named
   stale cards, the longest bills block (on the 30th of a 30-day month) and 15 long
   purchases come to exactly 1,600 characters, so all 15 are listed. The `BODY_MAX`
   backstop remains for anything longer.
7. **The A2P samples were regenerated** and the campaign description no longer mentions
   the previous four weeks. Re-filing them in Twilio is an operational step outside the repo.

## Related

- [[022-decision-digest-four-week-spend-history]] — supersedes: the `Last 4 weeks` block is removed.
- [[2026-11-21-decision-digest-reports-the-months-bills]] — amends decision 1: the month block's labels now carry their dates, and its figures stop at today.
- [[2026-11-08-decision-digest-lists-every-purchase]] — restores decision 3: the cap alone again covers the stated worst case.
- [[2026-10-12-constraint-plaid-date-is-the-posting-date]] — builds on: why `yesterday` is a sufficient fetch floor.
- [[2026-10-12-decision-digest-credit-cards-and-yesterday]] — see also: the rest of the message, unchanged.
