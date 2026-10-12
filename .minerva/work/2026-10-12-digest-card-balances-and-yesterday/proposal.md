# Proposal: digest-card-balances-and-yesterday

**Date**: 2026-10-12
**Status**: Draft
**Closes**: #37

## Goal

Reshape the daily digest SMS — the 7am scheduled text and the dashboard's "Text me
this" button, which both build their body through `digest_body` via the shared
`_digest_parts` seam in `app/notifications.py`:

1. **Balances block → credit cards only.** List only accounts whose `Account.type`
   is `credit` (case-insensitive), under a `Credit cards` header, each line printed
   exactly as today (`Citi · Double Cash ••1234: $612.40`, with `(reconnect needed)`
   when the institution is not syncing). Drop every other account type (checking,
   savings, investment, loan) and the `Net worth` line. Close the block with a
   `Total card debt: $X` line — the sum of the listed cards' balances.
2. **New `Yesterday` section**, covering the previous local calendar day
   (`today - 1`, where `today` is already the `APP_TIMEZONE` date the digest uses):
   - a summary line: how many purchases and their total;
   - every purchase over $100, largest first;
   - spending by category, largest first.

Unchanged: the `BRAND` header, greeting, budget line, `Week of` line, the
`Last 4 weeks` history, and the opt-out line.

Target shape:

```
Onerlaw LLC
Good morning — Mon Oct 12

Budget: $412 of $1,000 (41%) — $588 left
Week of Oct 11

Last 4 weeks
Sep 13–19: $842
Sep 20–26: $1,130
Sep 27 – Oct 3: $655
Oct 4–10: $918

Credit cards
Amex · Gold Card ••1008: $1,204.33
Citi · Double Cash ••1234: $612.40 (reconnect needed)
Total card debt: $1,816.73

Yesterday — Sun Oct 11
6 purchases: $287
Over $100
Whole Foods Market: $142.18
By category
Food and drink: $201
General merchandise: $86

Reply STOP to unsubscribe.
```

## Why

The user asked for it directly: the daily text should track credit-card debt (each
card plus the total owed), not every account and not a net-worth figure, and should
report what happened yesterday — overall, the big-ticket purchases, and where the
money went by category. The weekly budget line and four-week history aggregate a
day's activity away; nothing in the current text says what was bought yesterday.

## Approach

1. **One spend definition, one query (knowledge 022 decision 3).** "Purchase" means
   `spending.is_spend` (positive amount, not `TRANSFER*` / `LOAN_PAYMENTS`) over
   non-removed transactions, pending included — the budget line's definition and
   filter. *(Superseded by replan 2026-10-12:)* the Yesterday section selects rows
   **purchased** yesterday — `spending.purchase_date(txn)` = `authorized_date or date`
   — while the budget line and history stay keyed on `date`. Every Yesterday row is
   still counted in some printed week total, possibly in a different week bucket than
   its label implies. A purchase is never shown twice when Plaid supplies the same
   `authorized_date` on its pending and posted rows; see `replan.md` for the
   residuals.

   The existing `_week_totals` fetch spans `[week_start(today) - 4 weeks,
   week_start(today) + 7 days)`; yesterday is always `>= week_start(today) - 1 day`,
   inside that window, so **the already-fetched rows contain yesterday**.
   `_week_totals` returns only aggregates today, so it is refactored to also hand
   back the yesterday aggregate from the same row list (one fetch, three
   derivations). A new pure `spending.day_spend(transactions, day)` re-filters to the
   day (the defensive re-filter every aggregate here does) and returns a small
   NamedTuple: `count`, `total`, `large` (`[(label, amount)]` for amount > 100,
   descending), `by_category` (`[(category, total)]`, descending, ties by name). The
   digest keeps costing exactly one transaction query.
2. **Formatting rules.**
   - Over $100 is strict (`amount > 100`). Label = `merchant_name`, falling back to
     `description`, truncated to 32 characters (31 + `…`). At most 10 lines; beyond
     that a final `+N more` line. When none: `Over $100: none`.
   - Category = `Transaction.category` (Plaid personal_finance_category primary),
     humanized `FOOD_AND_DRINK` → `Food and drink`; null/empty → `Uncategorized`.
     At most 6 lines: with more than 6 categories, the top 5 plus `Other: $X` (the
     sum of the rest).
   - Individual purchases print dollars-and-cents (a specific amount, like a balance);
     the summary total and category totals print whole dollars (magnitudes to compare,
     like the budget and history lines). Rounded totals can therefore differ by cents
     from the itemised lines — accepted.
   - No purchases yesterday → the section is the header plus `No purchases.`; the two
     sub-blocks are omitted.
   - Length: with the caps above, a worst-case digest (8 cards, 11+ large purchases
     with 32-character labels, 7+ categories) stays under Twilio's 1600-character
     body limit; a test pins it. A typical body grows from ~300 to ~550 characters
     (UCS-2, so roughly 4 → 8 segments) — pennies a month at one recipient, accepted.
3. **Cards.** A single `_is_card(row)` predicate (`(row.type or '').lower() ==
   'credit'`) selects the rows in Python; the account query stays one query, trimmed
   to the columns still used. The total sums non-null balances **as printed** (raw
   `current_balance`, no sign flip — knowledge 016 decision 5), so an overpaid card's
   negative balance reduces it. Per-card lines keep `account_line`'s existing format
   (a negative card balance prints as the dashboard prints it, `$-12.34`); the total
   line formats a negative total as `-$X`. A stale card is listed (flagged) and
   counted. A null balance prints `—` and contributes nothing. No cards →
   `No linked credit cards.` and no total line.
4. **Remove the net-worth machinery** (knowledge 024 superseded at the user's
   request): `LIABILITY_TYPES`, `_is_liability`, `account_net_worth`,
   `net_worth_line`, `digest_accounts`, `_excluded_patterns`, `_pattern_matches`,
   `_warn_unmatched`, and `account_line`'s `excluded` / `unvested_discounted`
   parameters, plus all of their tests in `tests/test_notifications.py`.
   `NET_WORTH_EXCLUDED_ACCOUNTS` loses its only reader, so it is removed from
   `app/__init__.py` and `.env.example`; a value left set in Doppler is simply never
   read. `AccountRow` drops `slug` and `unvested`. Open issue #37 ("Set
   NET_WORTH_EXCLUDED_ACCOUNTS in Doppler", verified open 2026-10-12) becomes moot
   and is closed by this PR.
5. **`digest_body` signature** becomes `digest_body(today, spent, history, cards,
   card_total, yesterday, budget=WEEKLY_BUDGET)` — every content argument required,
   per the knowledge 022/024 rule that a default turns a forgotten argument into a
   silently short digest. `_digest_parts` stays the single seam both send paths call.
6. **A2P coupling (knowledge 022 decision 5).** Regenerate the three sample messages
   in `docs/twilio-a2p-campaign-resubmission.md` from the new `digest_body` — between
   them covering a full day with a `(reconnect needed)` card, a day with purchases but
   none over $100, and a day with no purchases — rewrite the campaign description's
   list of message contents (drop net worth; add card balances + total and the
   yesterday summary), and update the samples note (the only remaining parenthetical
   is `(reconnect needed)`). **Compliance flag for the final report:** the verbal
   opt-in script published at onerlaw.com/terms says the text carries "the balances
   of your linked accounts"; the message now carries card balances only plus
   yesterday's purchases. The script lives outside this repo and is not edited here,
   but if the campaign is already filed, the description and samples must be
   re-submitted and the terms page brought in line.
7. Update the `app/notifications.py` module docstring to describe the new content.
8. **At promote:** write a new decision entry for this change that supersedes
   knowledge 024 (supersession marker + `## Related` link), noting that 016 decision
   5 (raw balances, no sign flip) stays in force and that 016/022's "every account"
   descriptions of the balances block no longer hold.

### Candidate approaches considered

- **A (chosen) — pure aggregation over the existing single fetch.** As above.
- **B — SQL aggregates for yesterday** (`GROUP BY category`, `WHERE amount > 100`).
  Rejected: re-implements the `is_spend` exclusions in SQL (a third spend definition,
  which knowledge 022 decision 3 explicitly avoided) and adds queries the pin test
  forbids.
- **C — keep the net-worth machinery, hide it from display, apply
  `NET_WORTH_EXCLUDED_ACCOUNTS` to the card list instead.** Rejected: the user asked
  to remove net worth; the exclusion list existed to keep accounts out of net worth
  (its documented use: excluding a SoFi checking account — not a card), and keeping a
  config var with no purpose is dead surface.

## Success criteria

1. A `digest_body`-level test with checking, savings, investment, loan and two credit
   accounts lists only the two credit accounts under `Credit cards`, ends the block
   with `Total card debt:` equal to their sum, and the body contains no `Net worth`.
2. A no-card fixture renders `No linked credit cards.` and no total line; a negative
   card total renders `-$`; a negative card balance renders `$-` on its line.
3. With fixture transactions purchased (`authorized_date`, else `date`) yesterday,
   today and two days ago — plus a transfer and a refund yesterday — the `Yesterday`
   summary counts and totals only yesterday's `is_spend` rows; a pending row and its
   posted replacement (same `authorized_date`) yield one Yesterday entry across the two
   digests, a posted row with null `authorized_date` falls back to `date`, and a removed
   pending row is excluded; `Over $100` lists exactly yesterday's spend rows with
   amount > 100, largest first; `By category` sums yesterday's spend rows per
   humanized category, largest first, null → `Uncategorized`.
4. A day with no purchases renders `No purchases.`; a day with purchases but none over
   $100 renders `Over $100: none`.
5. The over-$100 list caps at 10 lines plus `+N more`; a long merchant name is
   truncated to 32 characters; more than 6 categories render as the top 5 plus
   `Other:`.
6. A worst-case body (8 cards, 15 large purchases with long labels, 12 categories) is
   under 1600 characters.
7. Both send paths (scheduled and manual) carry the card block and the `Yesterday`
   section end-to-end from DB rows, and the digest still issues exactly one
   transaction query (`test_digest_history_still_costs_one_transaction_query` keeps
   its `len(queries) == 1` assertion; only fixtures may change).
8. `grep -rn NET_WORTH_EXCLUDED_ACCOUNTS app tests .env.example` returns nothing.
9. The three samples in `docs/twilio-a2p-campaign-resubmission.md` are byte-identical
   to `digest_body` output for fixtures recorded in the work unit's scratchpad, and
   the campaign description no longer mentions net worth and names the new contents.
10. The full test suite passes.

## Open Questions

Interpretation choices made without asking (autonomous run); each is cheap to redirect:

- "Balances for all credit cards for the week" is read as each card's **current**
  balance — the schema keeps no balance history. Per-card weekly spend would be a
  separate change.
- "Remove … total net worth" is read as removing the net-worth line outright; the
  block's bottom line is the card-only `Total card debt`.
- "Transactions" in the yesterday summary and the over-$100 list means **purchases**
  (`is_spend`): refunds, income, transfers and card payments are excluded, matching
  the budget line's definition.
- The over-$100 list and the category summary are scoped to **yesterday**, like the
  summary line they follow (not the current week).
- *(Superseded by replan 2026-10-12, residuals a–c:)* a purchase first synced after
  its purchase day has passed is never shown in any `Yesterday` block (it still counts
  in the week totals); a posted row without `authorized_date`, or with one differing
  from its pending row's, can be shown a second time under its posting day. Accepted.
