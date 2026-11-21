# Proposal: digest-bills-outlook

**Date**: 2026-11-21
**Status**: Draft

## Goal

The user's request (verbatim): "So now that we know the general bills that we expect to pay ech month / week / etc. Can we go ahead and have the text message we send out show how much of the bills have been paid (e.g. list number of bills paid vs not paid, estimated pay amount for the month, etc), and then also split out the transactions with "bills" and "not bills" essentially so its easier to understand did we spend 4k or did 3.5k go to bills and 500 went to other things. It would also give me an idea of how much i expect to need to spend between now and the end of the month type of deal"

Add a month-to-date block to the daily digest SMS (`app/notifications.py`, both send paths via `_digest_parts`), between the `Week of …` line and `Last 4 weeks`:

```
November so far: $4,012
Bills $3,520 · Other $492

Bills: 7 of 11 paid
Still due: ~$1,180 (4 bills)
Bills this month: ~$4,700
```

- **November so far** = Bills + Other for the current local calendar month, keyed on `Transaction.date` (like the week totals and bill status).
- **Bills** = this month's charges (rows with amount > 0 and `date` in the month) of every *counted* bill — the exact set `/recurring` sums into its fixed monthly total (`excluded_reason is None`: active, sub-annual, not a transfer unless a user rule says it recurs). This includes bill payments that are not `is_spend` (rent paid by Zelle = TRANSFER_OUT, student loan = LOAN_PAYMENTS), so the total answers "where did the money go", not just "what did we buy".
- **Other** = this month's `is_spend` total (from the digest's existing spend fetch) minus the counted-bill charges that are themselves `is_spend`. So Other is every purchase that is not a bill payment, and Bills + Other adds up exactly.
- **Bills: P of N paid** — N = counted bills that belong to this month (charged this month, or expected to charge before month end); P = those with nothing more expected this month. This is month-based, not `/recurring`'s ±6-day badge window, so in drift cases the text's count can differ from the page's badges (stated in the PR body).
- **Still due** = Σ over counted bills of (remaining expected charges this month × that bill's typical per-charge amount), with the count of bills that have anything remaining.
- **Bills this month** = Bills (paid so far) + Still due: this month's projected **bill** total. Discretionary (Other) spending is deliberately not projected — there is no honest model for it; the weekly budget line already covers it.
- Whole dollars, `~` on estimates.
- No counted bills in the month → `Bills: none detected this month` (the split line still prints, with Bills $0). If bill detection fails, the digest still goes out: the spending line falls back to the `is_spend` total and says so — `November purchases so far: $X` — and one line `Bills: unavailable today` replaces the rest, so the fallback figure is never mistaken for the bills-inclusive total.

Unchanged: the weekly budget line (its semantics stay `is_spend` against $1,000 — bills paid by card still count toward it as today), Last 4 weeks, Credit cards, Yesterday (membership and `PURCHASE_LIST_MAX` = 15), dedup, the A2P brand/opt-out framing.

## Why

The digest reports spend but cannot tell fixed obligations from discretionary spending, so a $4k month reads the same whether $3.5k was rent/loans/utilities or groceries and dining. `/recurring` already knows the bills (detection + user rules + payment status); the user wants that knowledge in the morning text, including how much is still coming before month end.

## Approach

**B — cadence-aware month outlook per bill, reusing /recurring's detection verbatim (recommended).**

- `app/bills.py`:
  - `_finish_bill` also stores `occurrence_amount`: the typical single charge — the same P75-of-last-year per-date figure `monthly_amount` is built from, before the cadence factor (for a rule-forced monthly stream, the by-month figure). Refactor `_monthly_estimate` into an occurrence estimate × `MONTHLY_FACTOR` so `monthly_amount` is bit-for-bit unchanged.
  - New pure `month_outlook(bills, today) -> MonthBills` (dataclass: `paid_count`, `due_count`, `paid_total` (charges so far), `paid_spend` (the `is_spend` part of those charges, for the Other subtraction), `due_total`). Per counted bill: charges this month = positive rows with `date` in today's month. Remaining expected charges this month:
    - `monthly` (incl. rule-forced): 0 if any charge this month, else 1. (Deliberately "any charge this month" rather than `_payment_status`'s ±6-day window — the same rule rule-forced streams already use — so a drifting-day bill paid this month is not called due; see issue #58.)
    - `quarterly`: **calendar-month arithmetic**, not `cadence_days` (91 nominal days would put a bill charged on the 1st a month early: Oct 1 + 91 = Dec 31). 0 if charged this month; else 1 if the month three calendar months after `last_date`'s month is this month or earlier (overdue included); else the bill is not part of this month.
    - `biweekly` that is really twice a month (paid on the 1st and 15th — exactly two charges in each of ≥3 recent complete months): two a month, less those charged (added at review).
    - `weekly` / `biweekly`: count of `last_date + k·cadence_days` (k ≥ 1) falling in [today, month end]. Missed past occurrences are treated as skipped (weekly detection tolerates skipped sessions); today counts as still due because the digest runs at 7am.
    - A bill is in the month if it was charged this month or has a remaining charge; paid = in month with 0 remaining.
- `app/recurring_rules.py`: move `routes._rule_rows` here as `load_rules(session)` (plain rows, unchanged query; takes the session explicitly like the digest functions); `/recurring`, the preview form and the quick-mark route call it with `db.session`.
- `app/notifications.py`:
  - `_bill_outlook(session, today)`: `load_rules(session)`, `groups, _ = groups_for_detection()`, `detect_recurring_with_rules(groups, today, rules)`, `month_outlook(...)`. It is the **last** read in `_digest_parts` (after the spend fetch and the account fetch). On success it commits, persisting any merchant-index warm-up `groups_for_detection` did (its contract: "the caller commits"); nothing else is pending at that point and every value already read is plain data, so the commit expires nothing detection or the body needs (knowledge 2026-10-26). On **any** exception it logs, calls `session.rollback()` and returns `None` — a full rollback, not just a savepoint, because a dropped connection (the failure #68 addressed) leaves the session needing a rollback before the later `DailyDigest` write can run. The rollback loses only the index warm-up, which is redone on the next sync or page load.
  - Cost: detection reads every live transaction (the same unbounded read `/recurring` does on each page load) plus the rules; once a day at 7am, plus button presses. Accepted.
  - `_spend_totals` widens its single fetch to start at `min(week_start(today) − 4 weeks, first of month)` (on a Sunday the 30th/31st the month starts before the history window) and also returns the month's `is_spend` total. The spend aggregates still come from one query.
  - `digest_body` gains required `month_spend` and `bills` (`MonthBills | None`) arguments (the required-argument rule of 022 / 2026-11-08 kept); new pure `month_lines(today, month_spend, bills)` renders the block. `_digest_parts` supplies both, so the scheduled and manual bodies stay identical.
  - **Length**: the block adds at most ~140 characters (5-digit amounts, 2-digit counts). `PURCHASE_LIST_MAX` stays 15 — shrinking it would cut ordinary 13–15-purchase days the user asked to see in full. Instead this amends knowledge 2026-11-08 decision 3: the existing `BODY_MAX` backstop (which lists one fewer purchase while the body is too long) now also absorbs the bills block in the pathological worst case (8 long-named reconnect-needed cards, 5-digit totals). With a realistic 3 cards the cap alone still fits, pinned by test.
- Tests: pure `month_outlook` tests (monthly paid/due; weekly remaining occurrences; biweekly; quarterly charged on the 1st — due in the third calendar month, not the second; quarterly not this month; overdue quarterly; excluded bills ignored; rule-forced monthly), pure `month_lines` tests, through-the-send-path tests on seeded transactions (Zelle rent in Bills not Other; card utility in Bills not Other; grocery in Other; sums add up), failure-isolation tests (detection raising a plain error, and raising `OperationalError` — the digest is still sent **and** its `DailyDigest` row recorded), length tests, and the one-query test rewritten to call `_spend_totals` directly and assert exactly one `FROM transactions` statement (bill detection is a separate, separately-tested read).
- Docs: regenerate the three samples in `docs/twilio-a2p-campaign-resubmission.md` from `digest_body` and update the campaign description's content list; update the `app/notifications.py` module docstring. The PR body flags that if the campaign has been filed, the samples/description must be re-filed at merge, since `main` deploys on push.
- Knowledge: new decision entry for the bills block; it refines 022 decision 3 (one query for the spend aggregates; bill detection is a separate read) and amends 2026-11-08 decision 3 (the backstop, not the cap alone, covers the stated worst case once the bills block is present).

**Considered:**

- **A — reuse `/recurring`'s `payment_status` and `monthly_amount` as-is.** `P of N paid` = status counts; Still due = Σ `monthly_amount` of unpaid+upcoming bills. Simplest and identical to the page's badges, but wrong for non-monthly bills: a weekly bill's `monthly_amount` (4.33 charges) is either all due or all paid regardless of how many charges remain; a quarterly bill contributes 1/3 of a charge every month; knowledge 006 records weekly status as best-effort. Rejected: the "how much is still coming" number — the user's explicit goal — would be wrong for exactly the weekly bills (school/tutoring) this household has.
- **C — month projection without per-charge amounts: Still due = max(0, `monthly_amount` − charges so far) per bill.** No new field, cadence-agnostic. Rejected: a variable monthly bill paid below its P75 estimate (utilities $80 vs $100) would show $20 still due after it is paid, and the paid/due count has no clean definition.
- **D — also change the weekly budget to exclude bills, or tag bill lines in Yesterday.** Not asked; changes the budget's meaning and the Yesterday membership rule (2026-11-08 decision 2). Left out.

## Success criteria

1. Both send paths print the block, in the shape above, between `Week of …` and `Last 4 weeks`; pure tests pin exact lines for a typical month, a month with no counted bills, and the detection-failed case (`November purchases so far: $X` + `Bills: unavailable today`).
2. `month_outlook` pure tests: a monthly bill charged this month is paid; an uncharged one is due with its `occurrence_amount`; a weekly bill with N projected charges left in the month contributes N × `occurrence_amount` and is due; a quarterly bill last charged Oct 1 is not due in December and is due in January; a quarterly bill not expected this month is in neither count; excluded (transfer/inactive/annual) bills are ignored; a rule-forced monthly stream behaves as monthly.
3. Through `send_daily_digest` on seeded transactions: a counted Zelle (TRANSFER_OUT) bill paid this month is in Bills and the month total but not Other; a counted card-paid utility is in Bills, not Other; a non-bill purchase is in Other; Bills + Other equals the printed total.
4. If bill detection raises — a plain exception or an `OperationalError` — the digest is still sent and its `DailyDigest` row recorded, with `Bills: unavailable today`.
5. `monthly_amount` and the `/recurring` page are unchanged (existing bill and route tests pass unmodified apart from the moved rule loader).
6. `PURCHASE_LIST_MAX` is still 15. With 3 realistic cards, a worst-case bills block and 30 long purchases, all 15 are listed under 1600 characters; the pathological 8-card worst case stays ≤ 1600 via the backstop; the long-named-cards backstop test still passes.
7. Scheduled and manual bodies are identical (existing test passes); `_spend_totals` issues exactly one `FROM transactions` statement (test calls it directly).
8. The three A2P samples are regenerated from `digest_body` and include the bills block; the campaign description mentions it.
9. `uv run pytest` passes.

## Open Questions

- Re-filing the A2P campaign samples/description in Twilio is an operational step outside the repo; flagged for the user and in the PR body.
- Accepted residuals: a monthly bill whose charge drifts across a month boundary (paid Oct 31, next Dec 1) shows as due in November; a weekly stream that often skips sessions overstates Still due (each projected session counts); a weekly bill charged today counts as still due in the 7am text until its charge posts.
- "Bills" means *detected recurring* — the same set `/recurring` counts — not a list of obligations: a merchant visited on a regular cadence (a weekly grocery run) is counted as a bill until it is marked not recurring (one click on `/recurring`). Said in the PR body and the knowledge entry so the split is not over-trusted.
- `groups_for_detection` and the merchant index read the global `db.session`; `_bill_outlook` uses the `session` it is handed for the rules, the commit and the rollback, which is `db.session` at both call sites. `send_digest_now` still writes no `DailyDigest` row, but may now commit an index warm-up — its docstring says so.
