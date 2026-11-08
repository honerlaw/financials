# Proposal: recurring-detection-recall

**Date**: 2026-11-08
**Status**: Shipped (2026-11-08)

## Goal

Find more of the user's real recurring expenses on /recurring automatically, without a user rule. The trigger was two real bills the user named, which detection missed:

- a weekly appointment, a fixed amount paid by Zelle to a person;
- a new monthly kids' activity: a first charge at a different amount, then two charges at the same fixed amount about a month apart.

Fix the general causes, not the two instances. The user's direction: "we should in general attempt to detect as much as we can". Each fix generalizes to every stream of that shape.

## Why

Replaying the production history (read over HTTP, not committed) through the current detector gives three root causes:

1. **Skipped sessions break weekly regularity.** The appointment's median gap is 7 days, so it lands in the weekly bucket. But only about 60% of its gaps are within 7 ± 2. Skipped weeks give 14- and 21-day gaps, and school breaks give 84- and 88-day gaps. `_classify_cadence` needs 70% (`GAP_REGULARITY`), so it returns None over every history length since late 2024, even though the last 10 gaps are almost perfectly weekly. Even once detected, a single skipped week makes it inactive: the `active` rule is overdue ≤ 1.5 × 7 = 10.5 days. That drops it out of the total, and it flickers back next week.
2. **A Zelle payment to a person is excluded as a "transfer".** Plaid categorizes Zelle as `TRANSFER_OUT`, and `_is_transfer` excludes the stream from the total. Knowledge 2026-10-26 lists "rent paid by Zelle tagged TRANSFER_OUT would be excluded" as a known consequence. The stream is listed today only under "Possibly recurring", with a transfer badge.
3. **A new monthly bill is invisible for about three months.** Detection needs `MIN_OCCURRENCES` = 3, and "Possibly recurring" needs charges in 4 of the last 6 complete months. The activity has 2 same-amount charges (end of September, end of October) plus a first charge in the same calendar month as the second, at a different amount. That first charge breaks whole-group regularity (gaps 21 and 31; the 21-day gap is irregular). The same-amount bin, at 2 dates, fails `MIN_OCCURRENCES`.

## Approach

**A — targeted relaxations, each at the failing rule, each replayed against production history.** Three independent changes in `app/subscriptions.py` and `app/bills.py`:

1. **Weekly skipped sessions** (`app/subscriptions.py`).
   - `_classify_cadence` runs the plain 7 ± 2 test first. If that fails and at least `WEEKLY_SKIP_MIN_WEEKDAY_SHARE` = 0.4 of the charge days fall on the stream's most common weekday (`_weekday_share`), it retries with `_gap_is_regular(..., skips=True)`. That also accepts 14 ± 2 and 21 ± 2 days (`WEEKLY_SKIP_MULTIPLES = (2, 3)`): one or two skipped sessions.
   - The weekday guard was added at review. Without it, about 28% of random 3–14-day merchant histories passed as weekly. With it, about 4% pass, against 2% before. `test_random_three_to_fourteen_day_habits_rarely_pass_as_weekly` pins the rate.
   - Bucket selection by median gap is unchanged, so a stream with a 14-day median is still biweekly.
   - A weekly stream stays `active` until it is 23 days overdue (`_inactive_after_days`: 3 × 7 + 2, the largest gap the bucket calls regular). Before this change the limit was 10.5 days. Other cadences keep 1.5 × their gap.
2. **Zelle payments are not transfers** (`app/bills.py`).
   - `_is_p2p_payment` matches `\bZELLE\b`, case-insensitive, on an outflow row's raw `description`. A word match means "GAZELLE" does not count. In `_is_transfer`, such a row votes "not a transfer". Each row votes on its own.
   - `description` is already a detection column, so `_DETECTION_COLUMNS` and the index are unchanged.
   - This also changes the suggestion's transfer badge, which is `_is_transfer` on the whole group.
   - Income and `_is_card_payment` are untouched.
3. **New monthly pair** (`app/subscriptions.py` and `app/bills.py`).
   - `_build_stream(..., pair=True)` accepts exactly 2 distinct dates as a monthly stream with `new` True when `_is_new_monthly_pair` holds: consecutive calendar months, and a gap of 30 ± 6 days with no calendar slack. Recency is the ordinary `active` rule: at most 45 days since the last charge.
   - `_classify_cadence` is unchanged. Every stream dict carries `new`.
   - Only `_split_by_amount` passes `pair`, and only when the bin's rows are not mostly card payments or transfers (`pair=not _is_transfer(rows)`). Card payments and transfers stay excluded, as before.
   - Whole-group detection, rule streams and `detect_subscriptions*` are unchanged.
   - `_split_by_amount` still skips a bin holding the whole group, unless that bin is a pair.
   - **Naming.** A pair that holds all of the group's outflows (refund rows aside) is the merchant itself: its own name, `split_amount` None and the unsuffixed key. So its essential mark survives the third charge that makes it an ordinary whole-group stream. Any other pair is a `Name · $X` plan with the `@X` key.
   - The pair's row positions join `taken`, so the "Possibly recurring" suggestion sees only the other rows.
   - The page shows a `new · 2 months` badge beside the Flag link. The pair is counted (the user's decision). Without a third charge it lapses by the ordinary monthly rule.

**Considered and rejected:**

- **B — trailing-window retry.** If full history fails, classify only the last 180 days. Replay: it fixes the weekly appointment but adds 6 streams, mostly false (a grocery store as monthly, a retailer as biweekly, a subscription as weekly). Rejected on precision.
- **C — lower `GAP_REGULARITY` or `MIN_OCCURRENCES` globally.** This reopens knowledge 003 point 2 (irregular merchants passing as weekly) for every bucket. Rejected.
- **For new bills: "possibly recurring" only, not counted.** The user chose counting, with a badge.

**Replay evidence** (production history, today = 2026-11-08, no rules applied; the harness lives in the session scratchpad and is never committed; tests use synthetic fixtures only):

- **Change 1** adds exactly 2 weekly streams: the appointment, and another weekly provider. It flips no other stream's active flag.
- **Change 3** with the strict ±6 gap accepts 8 pairs: 0 whole-group pairs and 8 pairs inside larger groups.
  - 1 is the target activity.
  - 1 is already claimed by a user rule in production, so it does not double-count (rules claim rows before detection).
  - About 5 are subscription-like charges.
  - 1–2 are likely everyday-store coincidences, together under $50/month of the counted total. Each self-expires 45 days after its last charge and can be flagged in one click.

- **Change 2** newly counts exactly 1 stream, the appointment: it is the only Zelle outflow group. Its production descriptors do contain `ZELLE` ("… ZELLE PAYMENT TO").

**Accepted risks**, stated so review can audit them:

- **Weekly scope.** Change 1 lives in the shared `_gap_is_regular`/`_build_stream`, so it also applies to weekly income streams, rule streams whose detected cadence is weekly, and `detect_subscriptions`. Forced rule streams are monthly and are unaffected. Replay: no weekly income stream exists in production, and no other stream changed.

- **Weekly window.** A weekly stream now stays active, and counted, for up to 23 days after its last charge, up from 10.5. A cancelled weekly bill lingers about 2 weeks longer.
- **Weekly amount.** Weekly amounts stay at P75 × 52/12, so a stream with skipped sessions is overstated. The total deliberately leans high (knowledge 2026-10-26).
- **Zelle breadth.**
  - Any regular Zelle outflow now counts: rent, a sitter, or a regular payment to a family member.
  - A Zelle payment to one's own account at another bank would wrongly count, but that is rare.
  - Plaid's `category_detailed` cannot separate the cases, because Zelle to a person and transfers between one's own accounts commonly share the same `TRANSFER_OUT` detailed category. The descriptor is the available signal.
  - The vote is per row: in a mixed group, Zelle rows vote "not a transfer" and the other categorized rows vote as before.
- **Zelle grouping coupling.** Different Zelle payees can fuzzy-merge into one group (Open Questions). Once Zelle counts, such a merged group could count as one mislabelled stream. Today only one stray row is affected. Filed as #64.
- **Whole-group pairs.** Two same-amount charges at a merchant with no other history are the loosest case. The replay found none today. They are accepted for the canonical new-subscription shape, and bounded by the 45-day self-expiry, the `new` badge and the one-click Flag.
- **In-group pairs.** A whole-group pair whose third charge has a different amount becomes an in-group pair (`Name · $X`, `@X` key). An essential mark set on it in its whole-group form is then lost. This is the same key behaviour as the existing split.

**Knowledge amendments** (promoted as amendments at promote time):

- **003** (cadence-only detection): the weekly bucket counts 2× and 3× gaps as regular. The 70% gate and median bucket selection are unchanged.
- **2026-10-26** (fixed monthly total): Zelle outflow rows no longer vote "transfer". This reverses its "rent paid by Zelle would be excluded" consequence.
- **2026-11-07 split** (exact-amount split): a 2-occurrence monthly pair is accepted below `MIN_OCCURRENCES`, including a bin that holds the whole group, under a strict gap and recency.

## Success criteria

All tests use synthetic, seed-relative fixtures (knowledge 004). No real merchants or amounts appear in them.

1. A weekly series with skipped weeks (14- and 21-day gaps mixed in, at least 70% of gaps within 7 ± 2, 14 ± 2 or 21 ± 2) is classified `weekly` by `_classify_cadence`.
2. An irregular frequent-merchant series with gaps spread across 2–25 days is still rejected. A stream with a 14-day median is still `biweekly`. The existing irregular-merchant tests pass unchanged.
3. A weekly stream 20 days past its last charge is `active`, and its payment status still comes from the existing `_payment_status`, not `inactive`. At 24 days it is inactive. Non-weekly streams keep 1.5 × cadence.
4. An outflow stream whose rows are categorized `TRANSFER_OUT` with descriptions containing `ZELLE` has `excluded_reason` None, so it is counted. A `TRANSFER_OUT` stream without `ZELLE` is still `transfer`.
5. In a group with one odd-amount charge plus two same-amount charges 31 days apart in consecutive months, the latest at most 45 days ago, the pair is a counted monthly bill with `new` True. /recurring renders its `new` badge. The group then yields no "Possibly recurring" entry built from the pair's rows.
6. A whole-group pair (2 same-amount charges, nothing else) is a counted monthly bill named as the merchant, with an unsuffixed `merchant:` key.
7. These are not accepted:
   - two same-amount charges 18 days apart in consecutive months;
   - two charges 31 days apart whose latest is 50 days ago;
   - two charges 31 days apart in non-consecutive months.
8. A user rule whose pattern claims a pair's rows yields only the rule's stream, never a second detected pair stream.
9. When a third same-amount charge arrives about a month later, a whole-group pair becomes the ordinary whole-group stream: one stream, never two, with the same unsuffixed key and `new` False. An essential mark saved on the pair still applies. (A 3-charge group that still fails as a whole, and whose exact-amount bin holds only 2 dates, is an in-group pair; see the accepted risk "In-group pairs".)
10. A weekly income stream (deposits) with skipped weeks is detected as weekly, with the same 23-day active window.
11. Every stream dict from `detect_recurring_with_rules` carries `new` (False unless it is a pair).
12. `uv run pytest` passes.
13. After deploy, /recurring in production (read over HTTP) shows the weekly appointment counted as weekly and the new activity counted as monthly with the `new` badge. Rollback is a revert of the PR: nothing in the schema, the migrations or the persisted index changes.

## Open Questions

- **Latent, out of scope:** fuzzy grouping collapses different Zelle payees into one group. Their normalized descriptors share long boilerplate ("<name> payment id … zelle payment to"), and `SequenceMatcher` scores them above 0.82. Today only one stray row of another payee joins, but a second regular Zelle payee would be mixed in and could break both. Fixing it changes grouping (`GROUPING_ALGO_VERSION` bump, index rebuild), so it should be its own unit. Filed as #64.

## Deferred work
- #64 — Fuzzy grouping merges different Zelle payees into one merchant group (priority: high)
