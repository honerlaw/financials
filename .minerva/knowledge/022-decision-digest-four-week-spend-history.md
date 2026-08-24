# Daily digest carries four completed weeks of spend, not the running one

**Date**: 2026-08-23
**Type**: decision
**Summary**: The digest SMS gained a `Last 4 weeks` block between the budget line and the balances — the four COMPLETE Sun–Sat weeks before the current one, whole dollars, zero-filled; the running week stays exclusively in the budget line, both aggregates come out of one widened query, and the A2P sample messages were regenerated because filed samples must match live traffic.

**Context**: .minerva/work/020-digest-four-week-history

## Context

The digest ([[016-decision-daily-digest-notifier]]) answered "where does this
week stand" and "what is in each account", but nothing about whether this week
is normal. A $750 week reads very differently against four $650 weeks than
against four $1,200 weeks.

## Decisions

1. **The window is the four COMPLETE weeks, and excludes the running one.** The
   current week is already the headline budget line; its total is partial until
   Saturday, and a partial week sitting in a column of finished weeks reads as a
   drop that is not real. This was a genuine coin flip — "this week + 3 prior"
   was the alternative offered — and the user chose completed-weeks-only.
   `spending.recent_week_spend(transactions, today, weeks=4)` therefore returns
   `[(week_start, total)]` for `[week_start(today) - 4 weeks, week_start(today))`,
   oldest first.

2. **Zero-spend weeks are emitted, not skipped.** A week with no spend renders
   `$0`, so the list is always four rows — the same choice `daily_spend` makes
   for empty days. A skipped week would read as "no data" when it means "no
   spend", and would silently shorten the block.

3. **One spend definition, one query.** The history reuses `is_spend` /
   `week_start` rather than aggregating in SQL: week bucketing is date
   arithmetic that differs between SQLite and Postgres, and a SQL version would
   have to re-implement the category exclusions, giving the app a third spend
   definition ([[008-decision-dashboard-spend-and-weekly-budget]] already warns
   about the second one in `chat/tools.py`). `_week_spent` became
   `_week_totals`, which fetches the whole five-week span **once** and returns
   both the budget number and the history — both consumers re-filter what they
   are handed, so the wider fetch cannot inflate either, and the digest still
   costs a single transaction query (there is a test pinning that).

4. **`digest_body`'s `history` parameter is required, not defaulted.** A default
   of `()` would turn a caller that forgot the argument into a silently short
   digest; a `TypeError` is the better failure. `spending._week_label` was
   promoted to public `week_label` and reused for the row labels, so a week is
   named identically in the SMS and in the dashboard's weekly tracker
   (`routes._week_label` remains a separate, year-carrying variant for the
   transactions table).

5. **Changing the message means re-filing the A2P samples — that is now written
   down as a body-shape rule, not a `BRAND` rule.** The three sample messages in
   `docs/twilio-a2p-campaign-resubmission.md` were regenerated from the new
   `digest_body` and the campaign description gained a clause for the history.
   The campaign had not been filed yet, so this was free; after approval it
   would be a compliance obligation, since traffic that does not match filed
   samples is a violation. The doc previously named `BRAND` as the coupling —
   that was too narrow, and the note now names `digest_body` itself.

## Known limitations / operational

- **The body grew ~110 characters** (a typical digest is now ~250–290). It is
  UCS-2 because of `—`/`·`/`••`, so that is roughly two more segments — still
  pennies a month at one recipient, and the unit-016 followup on ASCII-ising the
  message is the place that gets revisited if it ever matters.
- **Headroom against Twilio's 1600-character limit shrank** by those same ~110
  characters. Still ~28 accounts before the ceiling; unchanged as a concern.
- The history inherits the spend definition's limitation verbatim: a
  null-category outflow counts as spend, so historical weeks containing
  uncategorised transfers read high.

## Related

- [[016-decision-daily-digest-notifier]] — extends
  the digest this block was added to; cadence, dedup and stale-balance rules are untouched.
- [[008-decision-dashboard-spend-and-weekly-budget]] — builds on
  the `is_spend` definition and Sun–Sat week boundaries the history is computed with.
- [[018-decision-on-demand-digest-trigger]] — see also
  why the "Text me this" button picked the new block up for free.
- [[024-decision-digest-net-worth]] — see also
