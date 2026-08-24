# `transactions/sync` is not the only account source — an investment-only Item's accounts arrive nowhere else

**Date**: 2026-08-24
**Type**: bug
**Summary**: `Account` rows were only ever created from `transactions/sync`'s accounts array, which omits brokerage accounts, so an investment-only Item never got a row and never rendered a dashboard card; `_refresh_balances` and `_refresh_investments` now create the rows they used to skip.
**Context**: .minerva/work/021-investment-account-rows (see git history if the worktree has been cleaned up)

## Context

A linked E*TRADE from Morgan Stanley stock-plan account never appeared on the
dashboard. It was connected, Active, syncing every hour with `✓ OK` on every
SyncLog row, and carried **0 transactions**. Re-connecting it — the documented
remedy for [[015-decision-liability-consent-requires-update-mode]], and a real
prerequisite for the `investments` consent — changed nothing, because consent
was only ever half the problem.

## Finding

- **`Account` rows had exactly one creation site**: `_upsert_accounts`, fed only
  by the `accounts` array `transactions/sync` returns
  ([[001-decision-plaid-accounts-piggyback-on-sync]]). Plaid's transactions
  product does not cover brokerage/stock-plan accounts, so for an
  investment-only Item that array comes back empty and nothing is written.
- **All three dedicated refreshes discarded the account.** `_refresh_balances`,
  `_refresh_liabilities` and `_refresh_investments` each did
  `if row is None: continue`. `/investments/holdings/get` could return real
  vested figures and they would be dropped for lack of a row to attach them to.
- **Nothing reported it.** A missing row is not an error condition on any of
  those paths, so the sync logged `✓ OK` and the app logs carried nothing. The
  bug was invisible for a day and was found only by comparing the production
  dashboard against the production institution list.
- **The fix is create-only in two places.** `_refresh_balances` creates a row for
  an account it has never seen; `_refresh_investments` does the same from the
  holdings response's `accounts` array, *before* its empty-holdings early return.
  An account that already has a row takes the pre-existing update path unchanged.
- **`PlaidClient.get_investment_holdings` became `get_investments`**, returning
  `(accounts, holdings)`. The rename was the point: a same-named method whose
  return shape changed from list to tuple would have let the seven existing
  `return_value = [...]` mocks destructure two holdings into `accounts, holdings`
  without raising.

## Implications

- **`/accounts/balance/get` and `/investments/holdings/get` are account sources,
  not just field refreshers.** This supersedes the part of
  [[001-decision-plaid-accounts-piggyback-on-sync]] that treats the piggyback as
  the sole account feed. What survives from 001 is its actual decision — no
  dedicated `/accounts/get` round-trip — and that still holds: both new sources
  are responses the sync already fetches. 001's rejection of `accounts/get`
  rested on the premise that `transactions/sync` returns the same accounts, which
  is false for this account class; the rejection now stands on cost alone.
- **The metadata/balance split of
  [[002-decision-plaid-balance-refresh-via-dedicated-endpoint]] is intact,
  deliberately.** Both new paths are create-only. The piggyback still owns
  metadata for every account it returns; balance/get still owns balances. A
  blanket `_upsert_accounts` call in `_refresh_balances` would have been fewer
  lines and would have silently reversed that split — and dropped two guards with
  it: the `balances is None` skip (which stops a response with no balances object
  from nulling a known balance) and the conditional `iso_currency_code` write
  (Plaid nulls `iso_currency_code` whenever `unofficial_currency_code` is
  populated, so an unconditional write clobbers a known code).
- **Creating rows introduced a write race that updating never had.**
  `plaid_account_id` is unique and `/api/sync` spawns an unsynchronized thread on
  every press of the dashboard's "Sync now" button — on top of the 7am job and the
  reconnect trigger — so two syncs can both see a new account missing. (This bullet
  originally said "on every dashboard load", which was never true; the race is real
  regardless of what starts the overlapping syncs. See
  [[029-pattern-only-the-call-site-is-authoritative-for-runtime-behaviour]].) The
  loser's `IntegrityError` is not a `plaid.ApiException`, so it would escape the
  refreshes' "never re-raises" contract *and* `_sync_institution`'s except clause,
  discarding that institution's already-upserted transactions and skipping every
  institution after it — silently, because the thread just dies.
  `_create_account_if_missing` does the insert inside `db.session.begin_nested()`.
  The savepoint, not the `except`, is the load-bearing part: catching the error
  without one leaves the session unusable and the sync dies one statement later.
- **A fixture that supplies the thing whose absence is the bug cannot catch the
  bug.** Every investments test seeded the brokerage account into the
  `transactions/sync` accounts array by hand, so the suite passed against code
  that could never create it — the same shape as
  [[020-pattern-injected-fakes-hide-construction-failures]]. Unit 019's proposal
  stated "`transactions/sync` returns the account and its balance; nothing else"
  as fact; it was never verified, and it is false for an investment-only Item.
- **Which endpoint actually surfaces this Item's stock plan is still unverified.**
  `/investments/holdings/get` is guaranteed by schema to carry investment
  accounts; `/accounts/balance/get` is only schema-*permitted* to. Both paths ship
  because answering that question wrong is what caused this bug. Confirming it
  needs the Item's `access_token`, which lives in a Postgres whose trusted-sources
  list admits only DO apps and tagged droplets — so it is a post-deploy
  observation, not a pre-merge one.

## Related

- [[001-decision-plaid-accounts-piggyback-on-sync]] — supersedes
  the "piggyback is the sole account feed" premise; its no-`accounts/get` decision stands.
- [[002-decision-plaid-balance-refresh-via-dedicated-endpoint]] — builds on
  the metadata/balance ownership split, preserved here by making both new paths create-only.
- [[021-decision-plaid-vested-value-piggyback-on-sync]] — corrects
  its claim that the E*TRADE account "showed a single balance on the dashboard" (it never rendered a card), and its reference to `get_investment_holdings` (renamed to `get_investments`, now returning a tuple).
- [[020-pattern-injected-fakes-hide-construction-failures]] — see also
  the same failure shape: the fixture supplied what the code could not produce.
- [[015-decision-liability-consent-requires-update-mode]] — see also
  the re-connect step, a real prerequisite here but not the fix.
