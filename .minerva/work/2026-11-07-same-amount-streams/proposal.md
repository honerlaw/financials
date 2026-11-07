# Proposal: same-amount-streams-and-suggestions

**Date**: 2026-11-07
**Status**: Implemented

## Goal
/recurring finds recurring charges that one-stream-per-merchant detection misses:
1. **Several fixed-price plans at one merchant.** When a merchant's rows, taken as a whole, are not detected as a stream, its outflows are split by exact amount. Each same-amount subset that is an active monthly stream becomes a stream of its own. Two plans whose combined dates fail detection then show as two monthly streams. Plans about half a month apart that today's detector already reads as one biweekly stream are left as they are (see Known consequences).
2. **Recurring spend with no schedule.** A collapsed **"Possibly recurring"** list shows merchants charged in most recent months that produced no stream as a whole. Each entry has a **Flag** link (to count it) and a **Not recurring** link (to clear it), both opening the existing rule form. Appointment-style charges are the typical case: the day and amount vary every month. The list is never counted, and the user decides each entry with a rule.

## Why
The user found missing recurring charges and said they "might be more than once a month / have their own frequency and dont fall on the same day". A local replay of production data, not committed, found two causes.

**Several plans in one merchant group.** Cadence is classified over the whole group. For plans billed on days that are neither about a month nor about half a month apart, every bucket's per-gap test fails. For example, plans on the 3rd and the 25th give alternating gaps of about 22 and 8 days. Today's `_classify_cadence` returns None for that pair over every history length tried. The replay also found:
- Splitting such groups by exact amount recovered several active monthly plans across a handful of merchants.
- No active weekly, biweekly or quarterly same-amount subset turned up.
- The non-monthly and annual subsets the split did produce were all inactive coincidences or transfers: the same restaurant order three times, two same-price purchases a year apart.
- Every accepted subset (active and monthly) looked like a real plan, apart from one transfer-categorized one, which is listed but not counted.

**Regular spend without a cadence.** Appointment-style payees are charged most months, but on varying days and at varying amounts. No cadence rule can admit them without also admitting groceries.

The user already has rules (knowledge 2026-11-07-decision-user-rules-correct-recurring-detection), and a forced-monthly rule stream is estimated from monthly totals. What is missing is a way to *find* candidates. In the replay, a list of merchants charged in 4 of the last 6 months was dominated by everyday merchants that are charged every few days. Requiring a median gap of at least 6 days between charge days removed the high-frequency ones, and it kept weekly appointment-style payees.

Production data informed this design. No production names, amounts, counts or account details are recorded here, and all fixtures are fictional (the repo is public).

## Approach (A — exact-amount fallback split + suggestions from leftovers)
- **Where it runs.** It runs in `detect_recurring_with_rules` (app/bills.py), on the groups left after rules claim their rows and after `merge_by_descriptor`, as today.
  - The callers that go through it all return sub-streams too: `/recurring`, `detect_recurring_from_groups`, `detect_bills` and `detect_bills_from_groups`. Tests see the change through these.
  - `detect_subscriptions_from_groups` is unchanged. No app page calls it any more: /subscriptions redirects to /recurring.
- **Split, only as a fallback.**
  - A group is split only when `_build_stream(group)` returns None. A group detected as a whole is never split, so every stream detected today is unchanged.
  - Only outflow rows (`amount > 0`) are split, by exact `amount`. Inflows are never split, because income must err low (knowledge 2026-11-06).
  - A same-amount subset is skipped only when it **is the whole group**. A group whose refunds broke whole-group detection still has each of its exact-amount bins tried. There is no extra attempt with all of its outflows together, which would recover variable bills and widen scope.
  - Each subset goes through `_build_stream` unchanged, so `MIN_OCCURRENCES`, `GAP_REGULARITY` and the calendar-month rule all apply.
  - A subset is accepted only if its cadence is **monthly** (`SPLIT_CADENCES = {'monthly'}`) **and** it is active.
    - **Annual is rejected** (`MIN_OCCURRENCES_ANNUAL` = 2 lets same-price coincidences in).
    - **Weekly, biweekly and quarterly are rejected** too. In the replay those were coincidences or transfers. Splitting one group into many exact-amount bins gives each bin its own chance to pass at `MIN_OCCURRENCES` = 3.
    - **Inactive subsets are rejected**, so past price changes and old coincidences add no Inactive clutter. Their rows stay among the group's remaining rows.
- **What an accepted sub-stream looks like.**
  - Its `name` is the group's display name plus the amount (`Example Co · $9.00`). It carries `split_amount` and shows a "same amount" badge.
  - Its Flag link pre-fills:
    - the pattern hint, computed from **the sub-stream's own rows**;
    - `amount_min = amount_max = split_amount`;
    - the label;
    - outflow.

    A ranged rule outranks an unranged one, so a rule normally takes the sub-stream over exactly. The rule matches that pattern and amount in **every** group, not just this merchant. The form's preview shows which rows it would claim before it is saved.
  - Payment status, the P75 estimate (the exact amount × 1) and the excluded reasons apply unchanged. A transfer-categorized sub-stream is listed under Transfers and never counted.
- **Suggestions ("Possibly recurring").** These are computed in the same pass and returned as `Recurring.suggestions`.
  - **Which groups qualify.** A group is a candidate when all of these hold:
    - it produced no stream as a whole;
    - it is not mostly **card payments**. Most categorized rows with `LOAN_PAYMENTS_CREDIT_CARD_PAYMENT` excludes it, since paying a card settles charges already counted. This is judged on the whole group;
    - its **remaining** outflow rows (those in no accepted sub-stream) have at least one charge in `SUGGEST_MIN_MONTHS` = 4 of the `SUGGEST_WINDOW_MONTHS` = 6 complete calendar months before today's month;
    - those rows' distinct charge days in the window have a median gap of at least `SUGGEST_MIN_MEDIAN_GAP_DAYS` = 6. This excludes everyday merchants charged every few days.
  - **Transfers stay in the list.** Other transfer-categorized groups are not excluded, because bills paid by transfer or P2P payment are a main way bills hide (the rules unit's Why). They carry a "transfer" badge and sort after every non-transfer entry.
  - **What each entry shows:**
    - the merchant name;
    - "N of last 6 months";
    - a typical month: the median of the nonzero monthly totals in the window;
    - the last charge date;
    - a **Flag** link (pattern hint from the remaining rows, label, outflow, action recurring);
    - a **Not recurring** link (the same fields with `action=not_recurring`).
  - **When the merchant also has an accepted sub-stream**, both links are omitted. Instead a note says to flag the same-amount stream first. Either unranged rule would also claim that counted stream's rows, and one rule cannot say "everything except $X". Once the sub-stream is taken over by its ranged rule, the remaining rows' suggestion shows both links again.
  - **Which rows each input uses.**
    - The transfer badge is judged on the whole group (`_is_transfer`), like the card-payment exclusion.
    - Months, typical month and median gap use the remaining outflow rows inside the window.
    - Last charge is the latest remaining outflow, which may fall in the current month.
  - **Ordering and placement.** Entries are sorted by transfer last, then typical month descending, then name. The list is a collapsed `<details>` placed after Not counted, rendered whether or not Not counted has rows, and it is never counted. A rule claims a merchant's rows, so a flagged or dismissed merchant normally leaves the list. The form's preview shows when a pattern would claim only part of it.
- **Unchanged.** Grouping, the index, `GROUPING_ALGO_VERSION`, cadence constants, the estimates for whole-group streams, rules, and the query count all stay as they are. All of this is pure and runs in the same pass.
- **Knowledge 003.** The split is a scoped override. A group that already failed detection gets a second, amount-partitioned chance: one test per exact-amount bin. That reopens 003 point 2, irregular merchants slipping in, for same-price habits. Monthly-only and active-only acceptance bound it. Even so, the calendar-month slack (15–45-day gaps across consecutive months) applies per bin, so a same-price purchase made once in each of several consecutive months passes. The replay found no such case among accepted subsets, and the post-deploy report rechecks this. Amount still never removes a stream that whole-group detection finds. Promote records this as an amendment to 003, with that caveat.

### Alternatives considered
- **B — amount clusters with a tolerance (e.g. ±5%).** This keeps a plan together across a small price change. But it merges different plans at similar prices and admits near-identical retail baskets. Exact amounts are what plans charge.
- **C — cluster by day of month.** This needs a day tolerance and breaks on bills paid on a drifting day, the case knowledge 2026-11-07-decision-monthly-gaps-are-regular-across-one-calendar-month exists for.
- **D — suggestions only.** The user rejected it and chose both.
- **A′ — prefer the split even when the whole group is detected weekly or biweekly.** This would also separate plans about half a month apart. But it changes streams detected today, and a true biweekly bill with a few repeated amounts could be split wrongly. It is not taken: the fallback keeps today's streams fixed, and the merged biweekly stream errs high (see Known consequences).

## Success criteria
1. **Split tests** (fixed dates, per knowledge 004; fictional):
   - Two monthly plans at different amounts on the 3rd and the 25th: the test first asserts `_build_stream(whole group)` is None, then that the group yields exactly two monthly streams named with their amounts.
   - A group detected as a whole is not split, and its stream is unchanged.
   - Same-amount subsets that are weekly, biweekly, quarterly or annual are rejected, and so is an inactive monthly subset.
   - Inflow rows are never split.
   - A same-amount subset with fewer than 3 occurrences yields nothing.
   - A one-plan merchant with a refund: the whole group fails because of the refund, and its outflow subset is detected.
   - Rows claimed by a rule are never split.
   - A transfer-categorized sub-stream is excluded as `transfer`, not counted.
   - A sub-stream's Flag fields carry its own pattern hint and exact amount.
2. **Suggestion tests:**
   - A merchant charged on irregular days at varying amounts in 4 of the last 6 complete months is suggested with months = 4 and the median monthly total.
   - 3 of 6 months gives no suggestion.
   - The current month does not count.
   - A median gap under 6 days gives no suggestion.
   - A merchant detected as a stream, a card-payment group and an inflow-only group are never suggested.
   - A transfer group is suggested with the transfer marker and sorted after non-transfers.
   - Rows in an accepted sub-stream are excluded from the group's suggestion. That suggestion carries neither link, only the flag-it-first note.
   - A `not_recurring` rule matching a suggested merchant removes it from the list.
   - Suggestions never change the headline totals.
3. **Route tests** (clock frozen with `freeze_time`, logging in inside the frozen block, per knowledge 2026-11-07-pattern-log-in-under-the-frozen-clock):
   - /recurring renders a sub-stream row with its amount in the name, the "same amount" badge, and a Flag link carrying `amount_min`/`amount_max`.
   - The "Possibly recurring" list renders with "N of last 6 months", typical month, last charge, and Flag and Not recurring links (the latter carrying `action=not_recurring`).
   - The list renders when Not counted is empty.
   - With neither present, the page renders as before.
4. `uv run pytest` passes, including the query-count tests and every existing detection test.
5. **After deploy**, report to the user only (nothing real is committed):
   - the counted expense total before and after;
   - every new same-amount stream;
   - the top of the "Possibly recurring" list.

## Known consequences
- **Plans about half a month apart** (e.g. the 1st and the 15th) are already detected today as one biweekly stream. That stream gets a merged name, an estimate of P75 × 26/12 (an overstatement), and a single payment day. It is not split. A rule with an exact amount range separates each plan.
- **A merchant that gains a second plan late** can still pass whole-group monthly detection for a while. It is then counted at about one plan's price, an undercount, until enough gaps are irregular. This is today's behaviour, kept by the fallback.
- **A group can move between forms as its history grows.** A borderline group can switch between one whole-group stream and several same-amount streams, and the headline moves with it.
- **A habitual same-price monthly purchase** can now be detected and counted. The user marks it not recurring.
- **Two plans at one merchant at the same price** stay merged and irregular. They surface in "Possibly recurring" instead.
- **A price change drops a plan for about a month.** The old-price subset turns inactive and is no longer accepted, and the new price needs 3 charges, so the plan is out of the total until then.
- **Everyday merchants charged less than about weekly** (fuel, pet supplies, occasional retail) still appear in "Possibly recurring" until marked not recurring. Each dismissal is a permanent rule listed under "Marked not recurring".
- **Own-account transfers** that recur monthly but irregularly can appear in "Possibly recurring", marked as transfers and sorted last.

- **A suggestion's "Not recurring" is an unranged rule.** A broad pattern hint can also claim a counted bill in another group. The rule form's preview lists every group it would take rows from (found in code review; documented, not changed).
- **The note beside a same-amount stream** says to add a rule for that stream first, not to Flag it, because that stream may be a transfer the user wants marked not recurring.

## Open Questions
- A lighter "dismiss" that does not create a rule is out of scope.
