# Weekly streams may skip sessions, Zelle payments are bills, and a new monthly bill counts from its second charge

**Date**: 2026-11-08
**Type**: decision
**Theme**: recurring-detection
**Summary**: Three recall rules: weekday-kept weekly skips, Zelle outflows not transfers, two-charge same-amount monthly pairs counted as `new`.
**Context**: .minerva/work/2026-11-08-recurring-detection-recall (see git history if the worktree has been cleaned up)

## Context

Two real bills that the user named were missing from /recurring:

- A weekly appointment paid by Zelle.
- A new monthly activity: a first charge at a different amount, then two charges at the same fee a month apart.

The user asked that the general causes be fixed ("detect as much as we can"), not the two instances. A replay of production history through the detector found three causes:

- Skipped weeks pulled the weekly stream under the 70% regular-gap gate.
- The Zelle payment was excluded as a `TRANSFER_OUT`.
- A new bill needed 3 charges, or 4 of 6 months to be suggested.

## Finding

1. **Weekly skipped sessions.** This lives in `app/subscriptions.py`.
   - `_classify_cadence` first runs the plain 7 ± 2 test. If that test fails and at least `WEEKLY_SKIP_MIN_WEEKDAY_SHARE` = 0.4 of the charge days fall on the stream's most common weekday, it retries with gaps of 14 ± 2 and 21 ± 2 counted as regular (`WEEKLY_SKIP_MULTIPLES`). Bucket selection by median gap is unchanged.
   - A weekly stream stays active for 23 days after its last charge (`_inactive_after_days`), not 10.5. Every other cadence keeps 1.5 × its gap.
   - Without the weekday guard, the 5–9, 12–16 and 19–23-day bands admitted about 28% of random merchant histories with gaps of 3–14 days (12 gaps, simulated). With the guard it is about 4%, against 2% before skips were allowed. Thresholds of 0.5 and above lost the real appointment for months, because Plaid posting dates drift its weekday.
2. **Zelle outflows are not transfers.** This lives in `app/bills.py`.
   - `_is_p2p_payment` matches `\bZELLE\b`, case-insensitive, on an outflow's raw descriptor. Such a row votes "not a transfer" in `_is_transfer`, and every row votes on its own.
   - Plaid files Zelle to a person under the same `TRANSFER_OUT` categories as moves between the user's own accounts, so the descriptor is the only signal that separates them.
3. **New monthly pairs.** This lives in `_build_stream(pair=True)` and `_split_by_amount`.
   - Two charges at one exact amount count as a monthly bill with `new` set when they fall in consecutive calendar months, 30 ± 6 days apart, with no calendar slack, and the stream is active. This is below `MIN_OCCURRENCES`.
   - Only the exact-amount split asks for this, so whole-group detection, rule streams and `detect_subscriptions` are unchanged.
   - Rows that are mostly card payments or transfers never form a pair.
   - A pair that holds all of a group's outflows is the merchant itself: it keeps its own name and unsuffixed key, so an essential mark survives the third charge. Any other pair is a `Name · $X` plan with the `@X` key.
   - The page badges a pair as "new · 2 months". It is counted. Without a third charge it lapses after 45 days, by the ordinary rule.

## Implications

- **This amends [[003-decision-subscriptions-cadence-only-detection]].** The weekly regularity test now accepts skipped sessions, with a weekday kept as corroboration. That is the first signal besides gaps to enter cadence classification. Amount still never gates.
- **This amends [[2026-10-26-decision-fixed-monthly-bills-total]].** Its consequence "rent paid by Zelle would be excluded" no longer holds.
  - Any regular Zelle outflow now counts, including a payment to family.
  - Different Zelle payees can fuzzy-merge into one group, which issue #64 tracks. Since Zelle now counts, such a merged group would count wrongly.
- **This amends [[2026-11-07-decision-split-undetected-groups-by-exact-amount]].** A whole-group bin is no longer always skipped: a pair is accepted. Two occurrences now pass, which is the coincidence risk that entry warned about. On the replay day, 8 pairs passed, 1–2 of them everyday-store coincidences. Each one self-expires and can be flagged in one click.
- **Weekly totals overstate a stream that skips sessions.** The total uses P75 × 52/12 with no discount for skips. A cancelled weekly bill also stays counted about two weeks longer. The total is meant to lean high.
- **Pattern: replay, then simulate.** When relaxing a cadence rule, one user's history is not enough. The production replay found no false positive here, but a seeded random-merchant simulation showed a 10× regression. Pin that rate in a test (`test_random_three_to_fourteen_day_habits_rarely_pass_as_weekly`).

## Related
- [[003-decision-subscriptions-cadence-only-detection]] — amended: weekly skipped sessions, weekday-corroborated
- [[2026-10-26-decision-fixed-monthly-bills-total]] — amended: Zelle outflows no longer count as transfers
- [[2026-11-07-decision-split-undetected-groups-by-exact-amount]] — amended: a two-charge monthly pair is accepted, including a whole-group bin
- [[2026-11-07-decision-monthly-gaps-are-regular-across-one-calendar-month]] — pairs deliberately do not use its calendar slack
- [[2026-11-07-decision-essential-marks-keyed-by-stream]] — why a whole-group pair keeps the unsuffixed key
- [[2026-11-07-decision-user-rules-correct-recurring-detection]] — rules claim rows first, so a rule-claimed pair never double-counts
- [[004-pattern-seed-relative-dates-in-time-sensitive-tests]] — fixed `today` in the new tests
