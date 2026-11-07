# A monthly gap is also regular when it spans exactly one calendar-month boundary and is 15–45 days long

**Date**: 2026-11-07
**Type**: decision
**Theme**: recurring-detection
**Summary**: Inside the monthly bucket, a gap counts as regular if it is within 30 ± 6 days, or if it crosses exactly one calendar-month boundary and is 15–45 days long.
**Context**: .minerva/work/2026-11-07-calendar-month-cadence (see git history if the worktree has been cleaned up)

## Context

Monthly bills that the user schedules by hand through online bill pay were missing from
/recurring entirely. Loan payments are the typical case. They are paid once every calendar
month, but the posting day drifts within a week or two, so the gaps between payments swing well
outside the monthly bucket's 30 ± 6 days. Fewer than `GAP_REGULARITY` (70%) of gaps were regular,
`_classify_cadence` returned None, and `_build_stream` never produced a stream to list or count.

## Finding

1. **Monthly gaps have a second way to count as regular.** `_gap_is_regular(earlier, later,
   nominal, tol)` in `app/subscriptions.py` accepts a gap if either:
   - it is within the bucket's tolerance, as before; or
   - the bucket is **monthly** (`nominal == 30`), the two dates fall in **consecutive calendar
     months** (`year * 12 + month` differs by exactly 1, so December → January counts), and the
     gap is within `MONTHLY_CALENDAR_SLACK` = 15 days of 30. Both ends are inclusive (15 and 45).
2. **Each part of the rule rejects something specific.**
   - The month-step test rejects gaps inside one month and gaps that skip a month.
   - The 15-day floor rejects short pairs that straddle a month boundary.
   - The 45-day ceiling rejects consecutive-month pairs 46–58 days apart. This costs a little
     recall in exchange for a bound on irregular merchants.
3. **Everything else is unchanged.**
   - Bucket selection by median gap (30 ± 6) is unchanged, so the buckets stay disjoint.
   - `MIN_OCCURRENCES`, `GAP_REGULARITY` and the other four buckets are unchanged.
   - The rule only adds regular gaps, so no stream that was detected before changes. A
     randomized comparison of the old and new classifiers confirmed this.
4. **This refines knowledge 003 rather than replacing it.** Detection still gates on cadence
   only, and most gaps must still be individually regular. What changes is what "regular" means
   for a monthly gap: it is now measured in calendar months, which is how a monthly bill is
   actually billed. Months are those of `date`, Plaid's posting date.
5. **A per-gap rule beat simply widening the tolerance.** Widening the monthly per-gap tolerance
   to ±13 days recovered the same bills, but it also counted a 17-day gap inside one month, and
   a ~42-day gap that skips a month, as regular. Lowering `GAP_REGULARITY` globally would loosen
   weekly detection, which is where 003's grocery-run false positives come from.

## Implications

- **Payment status disagrees with detection for these bills.** Knowledge 006 justified
  `PAYMENT_WINDOW = 6` as "what detection considers on-time", but that is no longer true for
  streams that pass through the calendar path. In some months a drifting bill shows a false
  "Unpaid" (issue #58).
- **Short histories are easier to admit.** At three occurrences, gaps of 18 and 42 days in
  consecutive months now read as monthly. This is accepted and pinned by a test.
- **Irregular merchants can slip in.** A merchant visited about once per calendar month cannot
  be told apart from a drifting bill, because 003 forbids an amount gate. The bounds limit this
  but do not eliminate it.
- **All checks share one group.** Normalization strips check numbers, so every paper check falls
  into one mixed-payee group. If that group posts once a month, it now reads as monthly and can
  count toward the expense headline.
- **The inactive threshold sits at the ceiling.** `INACTIVE_MULTIPLIER × 30` is 45 days, the same
  as the new gap ceiling. A drifting bill whose next payment posts late can briefly read inactive.
- **Tests for this rule use fixed dates.** The rule depends on calendar months, so seed-relative
  dates would flake with the run date (knowledge 004, pure-function clause). The route test
  freezes the clock; see [[2026-11-07-pattern-log-in-under-the-frozen-clock]].

## Related
- [[003-decision-subscriptions-cadence-only-detection]] — refined: a monthly gap's regularity is measured in calendar months; the shape and constants are unchanged
- [[006-decision-bills-payment-status-algorithm]] — the ±6 payment window no longer matches detection for calendar-path streams (issue #58)
- [[004-pattern-seed-relative-dates-in-time-sensitive-tests]] — fixed dates for the pure detector; a frozen clock for the route
- [[2026-10-12-constraint-plaid-date-is-the-posting-date]] — "calendar month" means the posting month
- [[2026-11-07-decision-merge-groups-renamed-by-plaid]] — the other recent recall fix on /recurring
