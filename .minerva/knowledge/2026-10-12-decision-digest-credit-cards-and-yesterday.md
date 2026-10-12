# Daily digest lists credit cards and their total debt, plus yesterday's purchases; net worth is gone

**Date**: 2026-10-12
**Type**: decision
**Theme**: daily-digest
**Summary**: Digest SMS shows only credit cards with a total-debt line, then yesterday's purchases; net worth removed.
**Context**: .minerva/work/2026-10-12-digest-card-balances-and-yesterday (see git history if the worktree has been cleaned up)

## Context

The digest ([[016-decision-daily-digest-notifier]]) printed every linked account's
balance and, since unit 022, closed that block with a net-worth line governed by
`NET_WORTH_EXCLUDED_ACCOUNTS` ([[024-decision-digest-net-worth]]). The user asked for a
different text: balances for credit cards only, the debt they add up to, no other
account types and no net worth — and a report of what was bought the previous day.

## Finding

1. **The balances block is cards only.** `digest_cards` keeps rows whose `Account.type`
   lowercases to `credit` (`_is_card`) — checking, savings, investment, loan and
   null-type rows are dropped — and closes the block with `Total card debt: $X`, the sum
   of the printed balances. The total adds balances **as printed** (raw
   `current_balance`, no sign flip), so 016 decision 5 still holds and an overpaid
   card's negative balance reduces the total; the line prints `$-12.34` like the
   dashboard, the total prints `-$12.34`. No cards → `No linked credit cards.` and no
   total. The only remaining per-line note is `(reconnect needed)`.
2. **Net worth and its exclusion list were deleted, not hidden.** `account_net_worth`,
   `LIABILITY_TYPES`, the `institution:account` matcher and `NET_WORTH_EXCLUDED_ACCOUNTS`
   (config + `.env.example`) are gone; the variable had no other reader and issue #37
   (set it in Doppler) closed with this unit. A value left in Doppler is simply never
   read. Keeping the matcher for cards was rejected: its documented use was excluding a
   checking account, and a config knob with no purpose is dead surface.
3. **A `Yesterday — <day>` section** reports the previous local day: `N purchases: $X`,
   every purchase over $100 (strictly, largest first, label `merchant_name` else
   `description` truncated to 32 characters, capped at 10 lines plus `+N more`, or
   `Over $100: none`), and `By category` (Plaid primary humanized, null →
   `Uncategorized`, capped at 6 lines as the top 5 plus `Other`). No purchases → `No
   purchases.` only. Individual purchases print cents; the day and category totals print
   whole dollars like the budget and history lines.
4. **One spend definition, one query — kept.** "Purchase" is `spending.is_spend` over
   non-removed rows, pending included. `spending.day_spend` aggregates from the same
   single fetch `_spend_totals` already made for the budget line and history
   ([[022-decision-digest-four-week-spend-history]] decision 3 is not superseded); the
   digest still issues exactly one transaction query, pinned by test.
5. **But Yesterday keys on the purchase date, not `date`.** Rows are selected by
   `spending.purchase_date` = `authorized_date or date`, while the week totals stay on
   `date` — see [[2026-10-12-constraint-plaid-date-is-the-posting-date]]. Every
   Yesterday row is still counted in some printed week total, possibly a different week
   bucket than its label implies (Sunday digest, Saturday purchase posted Sunday).
6. **`DaySpend` carries its `day`** so the section header and the numbers come from one
   value, and `digest_body(today, spent, history, cards, card_total, yesterday)` keeps
   every content argument required (the 022/024 rule).

## Implications

- **Message length is bounded by caps, not by luck.** The Yesterday section is the only
  activity-dependent part and is capped; a worst-case test (8 cards, 15 large purchases,
  12 categories) pins the body under Twilio's 1600-character limit. Card lines are
  uncapped: roughly 25+ cards would be needed to approach the limit alongside a
  worst-case Yesterday section. A typical body is ~550 characters (UCS-2, ~8 segments).
- **A2P coupling moved again.** The three samples in
  `docs/twilio-a2p-campaign-resubmission.md` were regenerated from `digest_body` and the
  campaign description rewritten (cards + total owed + yesterday's purchases; no net
  worth). The verbal opt-in script quoted there and published at onerlaw.com/terms still
  says "the balances of your linked accounts" — outside the repo, left matching the live
  page. If the campaign is already filed, the description and samples must be
  re-submitted and the terms wording brought in line.
- **Known residuals of the Yesterday key** (frequency per issuer unmeasured; the
  production DB is firewalled, so observe through the app): a posted row with no
  `authorized_date`, or with one different from its pending row's, can be shown a second
  time under its posting day; a purchase first synced after its day has passed is never
  shown in any Yesterday block (it still counts in the week totals).
- **016's and 022's descriptions of the balances block as "every account" no longer
  hold**; this entry is the current statement.

## Related

- [[024-decision-digest-net-worth]] — supersedes: net worth, the liability sign rule and `NET_WORTH_EXCLUDED_ACCOUNTS` were removed at the user's request.
- [[016-decision-daily-digest-notifier]] — extends: cadence, dedup and the raw-balance rule (decision 5) stand; the balances block is now cards only.
- [[022-decision-digest-four-week-spend-history]] — builds on: one spend definition and one widened query, reused for the Yesterday aggregate.
- [[2026-10-12-constraint-plaid-date-is-the-posting-date]] — see also: why Yesterday keys on `authorized_date` while week totals do not.
- [[018-decision-on-demand-digest-trigger]] — see also: the "Text me this" button carries the new content through the shared `_digest_parts` seam.
