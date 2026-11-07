# Proposal: calendar-month-cadence

**Date**: 2026-11-07
**Status**: Shipped (2026-11-07)

## Goal
A monthly bill paid exactly once per calendar month, on a day that drifts within roughly two weeks from month to month, is detected as a monthly recurring stream and appears on /recurring. These are typically bills the user schedules by hand through online bill pay, such as loan payments. Weekly, biweekly, quarterly and annual detection stay unchanged, and nothing detected today changes.

## Why
The user reported that several monthly loan payments are missing from /recurring. They are not listed at all, not even under "Not counted".

We replayed the production transactions locally through the real detector. Grouping is correct: each loan is one group of same-amount payments going back a long time. But `_build_stream` returns None for each of them because `_classify_cadence` rejects them.

These payments are manually scheduled, so the day of the month drifts within a window of a week or two. The gaps between consecutive payments therefore range well outside the monthly bucket's 30 ± 6 days. Detection requires at least 70% (`GAP_REGULARITY`) of gaps to be regular, and these streams fall just short, so they are dropped entirely rather than listed.

Production data informed this design. No production names, amounts, counts or account details are recorded here, because the repo is public.

## Approach
- **The rule.** In `app/subscriptions.py::_classify_cadence`, inside the **monthly** bucket only, a gap counts as regular in either of two cases:
  - it is within the existing ±6-day tolerance, as today;
  - its two dates fall in **consecutive calendar months**, and the gap is within ±`MONTHLY_CALENDAR_SLACK` = 15 days of 30 (15–45 days).
- **Month index.** The month index is `year * 12 + month` of `t.date`, so December → January counts as consecutive. `t.date` is Plaid's posting date (knowledge 2026-10-12-constraint-plaid-date-is-the-posting-date), so "calendar month" means the month the payment posted. A payment that posts in the following month is still covered by the ±6 path.
- **What stays the same.**
  - Bucket selection is unchanged: the median gap must still be within 30 ± 6 to pick the monthly bucket, so the buckets stay disjoint, and the monthly bucket still caps at a 36-day median.
  - `MIN_OCCURRENCES` (3) and `GAP_REGULARITY` (0.7) are unchanged.
  - Weekly, biweekly, quarterly and annual never run the new check.
  - Only the per-gap regularity test inside the monthly bucket can now reach 45 days, and only across exactly one month boundary.
- **What each check rejects.**
  - The month-step test rejects a gap inside one month (Jan 3 → Jan 21) and a gap that skips a month (Jan 30 → Mar 13), whatever the length.
  - The 15-day floor rejects a short pair across a month boundary (Jan 30 → Feb 2).
  - The 45-day ceiling rejects a pair in consecutive months that is 46–58 days apart (Jan 2 → Feb 27). That costs a little recall on genuinely once-a-month payments, in exchange for keeping a bound on irregular merchants.
- **Signature.** `_classify_cadence` takes the sorted, de-duplicated date list (same-day charges = one occurrence) and derives the gaps itself. Its only caller is `_build_stream`, and no test calls it directly. The per-gap decision is a small private helper, `_gap_is_regular(earlier, later, nominal, tol)`. Its calendar path applies only when `nominal` is the monthly bucket's 30 days. Both bounds are inclusive: 15 and 45 days are admitted.
- **Comment.** The `GAP_REGULARITY` comment now says "fraction of gaps that must be regular (`_gap_is_regular`)" (review fix).
- **No other changes.** Grouping, `GROUPING_ALGO_VERSION`, the persisted index, the expense and income estimates, and the transfer/income rules are unchanged. Payment status (knowledge 006, ±6-day window) is unchanged in this unit. Knowledge 006 justified `PAYMENT_WINDOW = 6` as "what detection considers on-time". For streams admitted by the calendar-month path that equivalence no longer holds; see Known consequences.
- **Knowledge 003.** Its shape is kept: gating stays cadence-only, and "most gaps must be individually regular" still holds. What "regular" means for a monthly gap is widened to the unit a monthly bill is billed in, the calendar month, which tunes a constant 003 calls provisional against real data. Promote writes a knowledge entry refining 003.

### Alternatives considered
- **B′: widen only the per-gap monthly tolerance to ±13 (17–43 days) and keep bucket selection at ±6.** On today's data B′ recovers the same bills. But it counts a 17-day gap inside one month and a ~42-day gap that skips a month as regular, and the local replay shows it admitting one additional irregular low-frequency charge. A rejects both shapes, because it encodes "once per calendar month" directly.
- **C: lower `GAP_REGULARITY` to 0.6 globally.** This loosens every bucket, including weekly, which is where knowledge 003's grocery-run false positives come from. A dominates C.

### Local replay (production data, not committed)
- Rule A newly detects the reported loan payments plus a few smaller recurring streams. No previously detected stream changes, and no inflow or income stream changes.
- One newly detected stream is a side effect, not a bill: paper checks. Normalization strips the check number, so every check falls into one mixed-payee "Check #…" group. That group now passes as monthly and can count toward the expense headline. This is accepted for now and called out in Known consequences.
- An unbounded variant (no 15–45-day bound) also admitted irregular retail visits. The bounded rule rejects them.

## Success criteria
1. **Unit tests** in `tests/test_subscriptions.py`. They use **fixed calendar dates and a fixed `TODAY`**, per knowledge 004's clause for pure functions that take `today` as a parameter. Rule A depends on calendar months, so seed-relative dates would flake with the run date. Amounts and names are synthetic.
   - (a) A bill paid once per calendar month on a drifting day is detected as one active monthly stream. The fixture is deterministic: its median gap is within 24–36, and fewer than 70% of its gaps are within 24–36, so the current rule rejects it.
   - (b) Gap boundaries, tested on `_gap_is_regular`, each with a near-identical twin:
     - in consecutive months, 15 and 45 days are regular, and 14 and 46 days are not;
     - a pair in consecutive months more than 45 days apart (Jan 2 → Feb 27) is not regular;
     - a 20-day pair inside one month is not regular;
     - a pair that skips a calendar month (Jan 30 → Mar 13) is not regular;
     - a December → January pair 37–45 days apart (Dec 5 → Jan 12) is regular. Only the calendar path admits that length, so the year wrap is actually exercised;
     - the calendar path is gated to the monthly bucket: a 20-day consecutive-month pair is not regular for the biweekly or quarterly buckets.
   - (c) An irregular merchant visited roughly once a month is not detected as monthly. The fixture is fixed and deterministic, with a median gap within 24–36, so the monthly bucket is selected and rule A itself rejects it. Its gaps fall inside one month or skip a month often enough that fewer than 70% pass.
   - (d) A three-occurrence history in consecutive months with gaps of 18 and 42 days **is** detected as monthly. This pins the accepted short-history trade-off; today it is rejected.
   - All existing detection tests pass unchanged.
2. **Route test** in `tests/test_bills.py`. It freezes the clock with `freezegun`, already a dev dependency, so `date.today()` in the route is fixed. /recurring then lists and counts a drifting-day monthly bill, and it appears in the expense headline. The fixture is one the current rule rejects.
3. `uv run pytest` passes, including the indexed-vs-in-memory parity tests and the /recurring query-count test.
4. **After deploy**, the loan payments the user reported missing appear on production /recurring as monthly streams. For each one, report to the user whether it is counted or which not-counted reason applies (for example, Plaid labelling it a transfer, or briefly "inactive" when the next payment is late). This report goes to the user only, never to the PR body, a knowledge entry or an issue. Check by reading the page; nothing real is committed. A newly detected bill can show "Unpaid" in a month where it was paid outside the ±6-day window. That is expected, and it is filed as a follow-up.

## Known consequences
- **Payment status.** Status still requires a payment within ±6 days of the median day of the month (knowledge 006). In some months, a drifting-day bill paid outside that window shows a red "Unpaid" badge and adds to the page's unpaid count, even though a payment posted that month. Changing status to "any payment this calendar month" would change 006 for every bill (and a late payment for last month could count for this one), so it goes to a follow-up GitHub issue rather than this unit (#58).
- **Short histories.** At exactly 3 occurrences, two consecutive-month gaps such as 18 and 42 days now pass, where today they are rejected. A short three-month burst of irregular charges can therefore appear as a monthly stream. This is accepted, because real three-charge subscriptions exist.
- **Irregular merchants visited once a calendar month** cannot be told apart from a drifting bill, because knowledge 003 forbids an amount gate. The bounds limit this but do not eliminate it.
- **Check group.** The mixed-payee check group can now count as a monthly expense (see Local replay).
- **Inactive margin.** The ceiling (45 days) equals the inactive threshold (1.5 × 30). A drifting bill whose next payment posts late can briefly read inactive. This is existing behaviour, but these bills sit near it.

## Open Questions
- Not addressed here, because each needs the user's input on what the payment is:
  - a monthly loan payment that Plaid labels a transfer is listed but not counted;
  - a monthly transfer to another internal account is grouped with all internal transfers;
  - checks are grouped together regardless of payee.

## Deferred work

- #58 — monthly bills paid on a drifting day can show a false "Unpaid" on /recurring (priority: high)
