# A merchant group detected as no stream is split by exact amount; irregular regulars become suggestions

**Date**: 2026-11-07
**Type**: decision
**Theme**: recurring-detection
**Summary**: When a merchant group fails whole-group detection, its outflows are binned by exact amount and each active *monthly* bin becomes a stream ("Name · $X"); groups still without a stream that were charged in 4 of the last 6 complete months (median charge-day gap ≥ 6, not card payments) are listed, uncounted, as "Possibly recurring" with Flag / Not recurring links.
**Context**: .minerva/work/2026-11-07-same-amount-streams (see git history if the worktree has been cleaned up)

## Context

Cadence is classified over a whole merchant group. Two failure shapes left real recurring spend off /recurring:
- **Several fixed-price plans at one merchant**, billed on days neither about a month nor about half a month apart (e.g. the 3rd and the 25th). The alternating gaps fail every bucket.
- **Regular spend with no schedule.** Appointment-style payees are charged most months on varying days at varying amounts, and no cadence rule admits them without admitting groceries.

## Finding

1. **The split is a fallback only.** `app/bills.py::_split_by_amount` runs only when `_build_stream(group)` is None, so every stream detected before stays as it was.
   - Only outflows are binned (income errs low, knowledge 2026-11-06).
   - A bin holding the whole group is skipped.
   - Each bin goes through `_build_stream` unchanged.
2. **Only active monthly bins are accepted** (`SPLIT_CADENCES = {'monthly'}`). On real data the weekly, biweekly, quarterly and annual bins were all coincidences or transfers. Binning one group into many gives each bin its own chance to pass at `MIN_OCCURRENCES` = 3, and annual needs only 2. Inactive bins add nothing.
3. **A sub-stream is an ordinary bill.** It has `split_amount` set, a "same amount" badge, and a Flag link pre-filled with its own rows' pattern hint and `amount_min = amount_max = split_amount`. The ranged rule outranks unranged ones and takes over exactly that plan. Every stream dict carries `split_amount` (None outside the split), so the template's `is not none` check never sees Undefined.
4. **Suggestions** (`Recurring.suggestions`, `_suggestion`) come from groups with no stream as a whole. A group qualifies when:
   - it is not mostly card payments (`_is_card_payment`, judged on the whole group);
   - its remaining outflows (those in no accepted sub-stream) were charged in `SUGGEST_MIN_MONTHS` = 4 of the `SUGGEST_WINDOW_MONTHS` = 6 complete months before today's;
   - the median gap between distinct charge days in the window is at least `SUGGEST_MIN_MEDIAN_GAP_DAYS` = 6.

   Transfer groups stay in the list, badged and sorted last. A suggestion beside an accepted sub-stream gets no links, only a note: any unranged rule would also claim the counted plan. Suggestions are never counted.

## Implications

- **This amends [[003-decision-subscriptions-cadence-only-detection]].** Amount now *partitions* a group that already failed, which reopens 003 point 2 (irregular merchants slipping in) for same-price habits. Monthly-only and active-only acceptance bound it. The calendar-month slack still applies per bin, though, so one same-price purchase in each of several consecutive months passes as a bill, and the user marks it not recurring. Amount never removes a stream that whole-group detection finds.
- **Plans about half a month apart stay one stream.** They are already detected as one biweekly stream, so they are never split (merged name, P75 × 26/12). Splitting them needs an exact-range rule.
- **A price change drops a plan for about a month.** The old-price bin goes inactive, and the new one needs 3 charges.
- **"Not recurring" from a suggestion is an unranged rule.** A broad pattern can also claim a counted bill in another group. The rule form's preview "taken from" list is the guard.
- **A lighter dismiss that writes no rule** was left out of scope. Each dismissal is a permanent rule under "Marked not recurring".

## Related
- [[003-decision-subscriptions-cadence-only-detection]] — amended: amount partitions an already-undetected group
- [[2026-11-07-decision-user-rules-correct-recurring-detection]] — sub-streams and suggestions are corrected with these rules
- [[2026-11-07-decision-monthly-gaps-are-regular-across-one-calendar-month]] — the slack that applies per bin
- [[2026-11-07-decision-merge-groups-renamed-by-plaid]] — the split runs on merged groups
- [[2026-11-06-decision-recurring-page-and-income-rule]] — why inflows are never split
