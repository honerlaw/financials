# Net worth in the digest: assets minus liabilities, unvested subtracted, exclusions in config

**Date**: 2026-08-24
**Type**: decision
**Summary**: The digest SMS closes its Balances block with one `Net worth:` line — assets minus `credit`/`loan` balances, with unvested equity netted out by SUBTRACTING `unvested_value` rather than substituting `vested_value`, and with accounts named by `NET_WORTH_EXCLUDED_ACCOUNTS` kept out of the total but still printed as `(not counted)`.
**Context**: .minerva/work/022-digest-net-worth

## Context

The digest ([[016-decision-daily-digest-notifier]]) enumerated balances but
never summarised them. Reading six balance lines and doing the arithmetic in
your head at 7am is the work a digest exists to have already done. The ask
arrived with an exclusion attached — one account must not count — and framed as
a list that would grow, not a one-off condition.

## Decisions

1. **Net worth is the first place in this app to read `Account.type` for
   meaning.** Everything else prints `current_balance` raw and deliberately
   never flips a sign ([[016-decision-daily-digest-notifier]] decision 5). A
   total cannot: Plaid reports a card's or a loan's balance as the amount
   *owed*, a positive number, so `type in {'credit', 'loan'}` is subtracted and
   everything else — including a null type on a freshly linked row — is added.
   Because the mapping was new and load-bearing, both signs are pinned by
   fixture-backed tests rather than assumed.

2. **Unvested equity comes out by subtraction, never by substitution.** The
   obvious implementation — "use `vested_value` when it is set" — is wrong, and
   was caught at the approach gate before any code existed.  `vested_value`
   sums *only* those holdings that report a known vested figure; a plain
   brokerage position in the same account appears in neither equity total
   ([[021-decision-plaid-vested-value-piggyback-on-sync]]). Substituting it
   would silently delete ordinary holdings from net worth. `current_balance -
   unvested_value` keeps them whole and discounts only the part that is not
   yours yet.

   The result is **clamped at zero**, mirroring the clamp
   `sync._refresh_investments` already applies to the unvested remainder: the
   balance and the holdings valuation come from different Plaid endpoints, so a
   stale price can put unvested above the account's own balance.

3. **One predicate drives both the arithmetic and the note.** `_is_liability`
   decides the sign *and* whether a line may claim `(unvested excluded)`.
   Deriving them separately is how a line comes to advertise a discount the
   total never applied — nothing in the schema stops a `credit` row from
   carrying an `unvested_value`, and the first version of this code had exactly
   that bug. Any future per-account note must come off the same predicate as
   the math it describes.

4. **Exclusions are config, and an excluded account stays visible.**
   `NET_WORTH_EXCLUDED_ACCOUNTS` parses like `BUDGET_ALERT_RECIPIENTS`
   ([[011-decision-doppler-hybrid-config]]) — comma-separated
   `institution:account` patterns, case-insensitive, institution half matched as
   a substring of slug or display name, account half matched exactly against the
   mask or as a substring of the name. **Both halves must match**, so a pattern
   is always anchored to one institution and excluding "the SoFi checking
   account" cannot take the Truist one with it.

   The two failure modes get different mitigations, on purpose. A pattern
   matching **nothing** is returned as data by the pure matcher and logged as a
   warning by the impure caller — silent no-match is the failure this feature
   cannot afford, because the user believes an account is excluded and the total
   quietly disagrees. A pattern matching **too much** is caught by the excluded
   account *staying in the message*, marked `(not counted)`: an unexpected
   parenthetical in the morning text is the report. Hiding excluded accounts
   would have removed that signal.

5. **One seam, so the button and the 7am job cannot drift.** `_digest_parts`
   fetches, derives and returns the whole argument tuple; both `send_daily_digest`
   and `send_digest_now` call it. `_account_balances` became `_account_rows`,
   returning an `AccountRow` NamedTuple carrying the slug, type and unvested
   value the total needs but the message never prints — one widened query, two
   pure derivations, the shape [[022-decision-digest-four-week-spend-history]]
   established. `digest_body`'s new `net_worth` parameter is required for that
   entry's reason: a default turns a caller that forgot it into a silently wrong
   digest instead of a `TypeError`.

## Known limitations / operational

- **The variable must be set in Doppler**, not just documented in
  `.env.example` ([[011-decision-doppler-hybrid-config]]). Until it is,
  production counts every account — the feature fails *open*, which is the
  right direction (a number that is too complete beats a missing digest) but is
  still wrong.
- **The institution half is a substring match**, so an over-broad pattern is
  possible by construction. This is a deliberate trade for usability — the
  display name Plaid returns is not something a user types from memory — and it
  is why the `(not counted)` suffix stays in the message.
- **`Account.mask` and `Account.name` are Plaid's mutable strings.** An
  institution-side rename turns a pattern into a no-op; the warning log is what
  surfaces that, and nothing re-validates patterns outside a send.
- **The message grew** by a blank line, the net-worth line, and a parenthetical
  on any excluded or discounted account. It is already UCS-2; headroom against
  Twilio's 1600-character ceiling shrinks accordingly, unchanged as a concern.
- **A2P samples were regenerated and the campaign description gained a
  net-worth clause.** Both halves move together — the filed samples *and* the
  description's list of what a message contains — and the doc's coupling note
  now names a new parenthetical as a trigger, not just a new section.

## Related

- [[016-decision-daily-digest-notifier]] — extends
  the digest this line closes; its "print raw, never flip a sign" rule is what made the liability decision a deliberate exception rather than an oversight.
- [[021-decision-plaid-vested-value-piggyback-on-sync]] — builds on
  what `vested_value` and `unvested_value` actually sum, which is why net worth subtracts the second rather than substituting the first.
- [[022-decision-digest-four-week-spend-history]] — builds on
  the one-widened-query shape and the required-parameter rule, both reused verbatim.
- [[011-decision-doppler-hybrid-config]] — see also
  where the exclusion list actually has to be set for production to see it.
- [[018-decision-on-demand-digest-trigger]] — see also
  the button that picks this up for free, now structurally rather than by hand.
