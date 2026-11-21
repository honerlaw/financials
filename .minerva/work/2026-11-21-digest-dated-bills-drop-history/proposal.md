# Proposal: digest-dated-bills-drop-history

**Date**: 2026-11-21
**Status**: Draft

## Goal

The user's request (verbatim): "lets remove the last 4 weeks piece, and then for the bills and stuff, can you denote the explicit start / end date of the time period its looking at"

Two changes to the daily digest SMS (`app/notifications.py`, both send paths via `_digest_parts`):

1. **Remove the `Last 4 weeks` block** (header + four week lines + its blank line).
2. **Date every line of the month block with its explicit period.** Shipped in #69 as:

```
November so far: $4,012
Bills $3,520 · Other $492

Bills: 7 of 11 paid
Still due: ~$1,180 (4 bills)
Bills this month: ~$4,700
```

becomes (today = Sat Nov 21):

```
Spent Nov 1–21: $4,012
Bills $3,520 · Other $492

Bills Nov 1–30: 7 of 11 paid
Still due by Nov 30: ~$1,180 (4 bills)
Bills total Nov 1–30: ~$4,700
```

- `Spent <1st>–<today>` — the period the spend total and its Bills/Other split cover. Enforced, not nominal: `spending.month_spend` and `bills.month_outlook`'s charges-so-far now both take rows dated from the 1st **through today** (previously any date in the month — a future-dated row is not expected from Plaid, but the label must not depend on that). At 7am today's rows are almost always none.
- `Bills <1st>–<month end>` — the counts are over the whole calendar month's bills.
- `Still due by <month end>` — what is still expected before the month ends. Only the end date is stated, because that is the only bound the computation enforces for every cadence: an unpaid monthly bill normally charged on the 5th, an overdue quarterly bill, or a missed twice-a-month charge are all still due though their usual date has passed; only weekly/biweekly projections start at today.
- `Bills total <1st>–<month end>` — the projected bill total for the month.
- A one-day range prints one date: on the 1st `Spent Nov 1: $0`. Ranges never cross a month. Same-month ranges use the unspaced en dash of the week-line style (`Nov 1–21`, like `Jul 5–11`).
- Variants: `Still due by Nov 30: none` when nothing remains; `Bills Nov 1–30: none detected`; detection failure → `Purchases Nov 1–21: $X` + blank + `Bills: unavailable today`.

Unchanged: the budget line and `Week of …`, Credit cards, Yesterday (already dated), the length cap and backstop, dedup, and #69's arithmetic except that the month's spend and bill charges so far now stop at today (above).

## Why

The user finds the four-week history not worth its lines, and "so far" / "still due" / "this month" leave the reader to work out which dates each figure covers.

## Approach

**A — inline the range into each label (recommended).**

- `app/notifications.py`:
  - Delete `HISTORY_WEEKS`, `history_line` and the history block in `digest_body`; drop `history` from `digest_body`'s signature (still all-required arguments) and from `_digest_parts`.
  - `_spend_totals` returns `(week spend, month spend, yesterday)`. Its single fetch shrinks from `min(week_start − 4 weeks, 1st of month)` to `min(week_start(today), 1st of month, yesterday)` — `yesterday` because when today is Sunday, yesterday is before this week's start. It is a sufficient floor for Yesterday's purchase-date-keyed rows because Plaid's `date` is the posting date and never precedes `authorized_date` (2026-10-12 constraint), so a row purchased yesterday has `date` ≥ yesterday; the docstring keeps saying so. Still one query.
  - `spending.month_spend` sums rows dated from the 1st through `today`; `bills.month_outlook` ignores a bill's charges dated after today — for its paid total and its paid/due decision alike, so the two always agree.
  - New pure `_period(start, end)` → `Nov 1–21` / `Nov 21` (same-month ranges only). `month_lines` uses it with `month_start(today)`, `today` and the month's last day.
- `app/spending.py`: delete `recent_week_spend` (only the digest read it) and its tests; `week_label` stays (dashboard tracker).
- Tests: update `month_lines` exact-line tests to the dated labels; add the 1st-of-month single-date case; a row dated after today is in neither the spend total nor the bills paid so far; rewrite the block-ordering test against `Credit cards` instead of `Last 4 weeks`; assert no `Last 4 weeks` / week-history line; Sunday case — a purchase made Saturday is still in Yesterday; the one-query test unchanged; length tests updated (shorter body).
- Docs: regenerate the three A2P samples from `digest_body`; drop "the total they spent in each of the four previous weeks" from the campaign description; add a provenance line that this unit removed the `Last 4 weeks` block and dated the month labels; update the module and `month_lines`/`digest_body` docstrings.
- Knowledge: new decision entry — supersedes `022-decision-digest-four-week-spend-history` (the block is gone) and updates `2026-11-21-decision-digest-reports-the-months-bills` (labels now carry their dates).

**Considered:**

- **B — one dated header over unchanged labels** (`November (Nov 1–30)` then the #69 lines). One line to change, but "so far" still leaves the end date implicit, and "Still due" the start — exactly what the user asked to make explicit. Rejected.
- **C — also re-label the week line `Week of Nov 15` as `Nov 15–21`.** Not asked ("for the bills and stuff"); the week line already names its start and is the dashboard's wording. Left out.

## Success criteria

1. No digest body contains `Last 4 weeks` or a week-history line; `HISTORY_WEEKS`, `history_line` and `recent_week_spend` no longer exist in `app/`, `tests/` or `docs/`.
2. `month_lines` prints exactly the dated shape above for Sat Nov 21; on the 1st the spend label is a single date; the `none`, `none detected` and unavailable variants carry their dates. Pinned by pure tests.
2a. A row dated after `today` in the current month is counted in neither `month_spend` nor `MonthBills.paid_total`, and does not make its bill paid (pure tests), so `Spent Nov 1–21` covers exactly what it names.
3. `_spend_totals` still issues one transaction query, and on a Sunday a purchase made Saturday still appears in Yesterday (test).
4. Both send paths still produce identical bodies; the Bills/Other split test through `send_daily_digest` passes with the dated labels.
5. The three A2P samples are regenerated from `digest_body`; the campaign description no longer mentions the four previous weeks.
6. `uv run pytest` passes.

## Open Questions

- Re-filing the A2P samples/description in Twilio is operational, flagged in the PR body.
