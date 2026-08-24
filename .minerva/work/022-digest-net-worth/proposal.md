# Proposal: digest-net-worth

**Date**: 2026-08-24
**Status**: Draft

## Goal

The daily digest SMS gains a single **total net worth** line, computed from the
linked-account balances it already prints, closing the Balances block:

```
Balances
SoFi · Checking ••1234: $412.00 (not counted)
Truist · Checking ••3390: $4,880.02
Citi · Double Cash ••1234: $612.40

Net worth: $4,267.62
```

Some accounts must not feed that total. The list is configuration, not code:
`NET_WORTH_EXCLUDED_ACCOUNTS` starts holding the SoFi checking account and
grows by a comma.

## Why

The digest answers "where does this week stand" (budget line), "is this week
normal" (the four-week history, unit 020) and "what is in each account"
(balances, unit 016). It does not answer "how am I doing overall" — the one
number that summarises the balance block instead of enumerating it. Reading a
column of six balances and doing the arithmetic in your head at 7am is exactly
the work a digest exists to have already done.

The exclusion mechanism is the load-bearing half of the ask. One account should
not count today, and the user's framing — "we might exclude others as well in
the future" — makes this a list that changes over time, not a one-off condition.

## Approach

### 1. One widened query, two pure derivations

`_account_balances(session)` becomes `_account_rows(session)`, selecting
`Institution.name`, `Institution.slug`, `Account.name`, `Account.mask`,
`Account.current_balance`, `Institution.status`, `Account.type` and
`Account.unvested_value`. Two pure functions run over those rows: one produces
the display tuples `digest_body` already consumes, the other computes the total.

This mirrors `_week_totals`, which unit 020 established as the shape for this
module — one wide fetch, consumers re-filter what they are handed
([[022-decision-digest-four-week-spend-history]]). Computing the total in SQL
was rejected for the same reason that entry rejected SQL week-bucketing: it
would give the app a second definition of the rule, in a dialect-sensitive
`CASE` expression, and it cannot express the unvested adjustment cleanly.
Extracting a shared `app/networth.py` was rejected as premature — the seed
scopes this to the text message and there is no second consumer.

### 2. What the total actually sums

- **Liabilities are subtracted.** `Account.type in {'credit', 'loan'}` is a
  liability; its `current_balance` is Plaid's amount *owed*, a positive number
  ([[016-decision-daily-digest-notifier]] keeps balances raw — no sign flipping
  anywhere in the app today). Every other type, including `None`, is an asset
  and is added. This is the first place in the codebase to read `Account.type`
  for semantic meaning, so both signs get fixture-backed tests rather than
  being assumed.
- **Unvested equity is discounted — by subtracting `unvested_value`, not by
  substituting `vested_value`.** `vested_value` is the sum of *only* those
  holdings that report a known vested figure; a plain brokerage position in the
  same account contributes to neither total
  ([[021-decision-plaid-vested-value-piggyback-on-sync]]). Substituting it would
  silently drop the value of ordinary holdings sitting alongside the equity
  comp. `current_balance - unvested_value` keeps plain holdings at full weight
  and discounts only the unvested portion. A null `unvested_value` subtracts
  nothing.
- **A null `current_balance` contributes 0.** The account still prints its `—`
  line, so the gap is visible rather than silent.
- **A stale account still counts**, at its last-known balance. Its line already
  carries `(reconnect needed)`; dropping it from the total would understate net
  worth far more badly than a slightly old number does.

### 3. Exclusions are configuration

`NET_WORTH_EXCLUDED_ACCOUNTS` parses exactly like `BUDGET_ALERT_RECIPIENTS` and
`CHAT_MODELS` — split on comma, strip, drop empty. Each entry is
`institution:account`, matched case-insensitively:

- the institution part must match `Institution.slug` or `Institution.name`
  (substring, so `sofi` matches `SoFi`);
- the account part must equal the `mask` or be a substring of `Account.name`.

Both halves must match, so a bare `checking` cannot reach across institutions.
An entry with no colon excludes every account at that institution. Unset means
nothing is excluded — the feature is inert by default, like every other optional
config in this module.

Two independent signals catch a bad entry. An entry matching **nothing** is
returned as data by the pure matcher and logged as a warning by the impure
shell, so the pure functions stay pure. An entry matching **too much** shows up
in the next morning's text as an unexpected `(not counted)` line — which is why
excluded accounts stay listed rather than disappearing.

### 4. Message shape

`digest_body` gains a **required** positional `net_worth` parameter after
`history`. Required, not defaulted, for the reason unit 020 gave for `history`:
a default would turn a caller that forgot it into a silently wrong digest
instead of a `TypeError`.

The line renders in dollars and cents, matching the balance lines it terminates
rather than the whole-dollar budget and history lines, and sits after the
Balances block, before the opt-out line. It is omitted entirely when there are
no linked accounts, where `Net worth: $0.00` under "No linked accounts." would
be noise.

`account_line` gains two suffix flags. `(not counted)` marks an excluded
account. `(unvested excluded)` marks an account whose printed balance is
knowingly larger than its contribution to the total — the same courtesy the
exclusion suffix provides, applied to the other case where a line and the total
do not reconcile. Both combine with the existing stale suffix, e.g.
`(reconnect needed, not counted)`.

### 5. A2P samples and description

Changing the body means re-filing the campaign's sample messages
([[022-decision-digest-four-week-spend-history]] decision 5). All three samples
in `docs/twilio-a2p-campaign-resubmission.md` are regenerated from the new
`digest_body`, **and** the campaign-description prose in "Field-by-field
answers" gains a net-worth clause — unit 020 updated both halves, and the
description currently describes only budget, history and per-account balances.
The campaign has not been filed yet, so this is free now and a compliance
obligation later.

## Success criteria

1. `digest_body` renders a `Net worth: $X.XX` line after the Balances block and
   before the opt-out line, and omits it when no accounts are listed.
2. The total adds assets and subtracts `type in {'credit','loan'}` balances,
   with fixture-backed tests pinning both signs.
3. An account with a non-null `unvested_value` contributes
   `current_balance - unvested_value`; a null `current_balance` contributes 0;
   a stale account still contributes.
4. Accounts matched by `NET_WORTH_EXCLUDED_ACCOUNTS` are excluded from the
   total, still listed, and suffixed `(not counted)`; matching is
   case-insensitive on both halves and requires both to match.
5. An exclusion entry matching no account is surfaced as data by the pure
   matcher and logged as a warning by the caller.
6. Both `send_daily_digest` and `send_digest_now` carry the new line, and the
   digest still costs one transaction query and one account query.
7. `NET_WORTH_EXCLUDED_ACCOUNTS` is wired in `app/__init__.py` and documented in
   `.env.example`; unset excludes nothing.
8. The three A2P sample messages are regenerated and the campaign description
   gains a net-worth clause.
9. `pytest` passes.

## Open questions

None blocking. Three settled with the user at intake: an excluded account stays
listed rather than disappearing; unvested equity does not count toward net
worth; exclusions are Doppler config rather than a settings-page toggle.

## Out of scope

- Any dashboard or UI display of net worth.
- A per-account exclusion toggle on `/settings` (offered and declined at intake;
  worth revisiting if the config list gets long or a mask ever changes).
- Any DB migration — `type`, `unvested_value` and `slug` are existing columns.

## Operational

`NET_WORTH_EXCLUDED_ACCOUNTS` must be added to the Doppler `onerlaw` project for
production to see it. `.env.example` documents the variable but does not
populate Doppler ([[011-decision-doppler-hybrid-config]]) — same as
`BUDGET_ALERT_RECIPIENTS`. Until it is set there, production computes net worth
over every account.
