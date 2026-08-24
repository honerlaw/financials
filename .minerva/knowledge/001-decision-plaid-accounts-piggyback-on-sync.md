# Plaid `transactions_sync` already returns the institution's accounts — piggyback instead of calling `accounts_get`

**Date**: 2026-05-20
**Type**: decision
**Summary**: Account metadata is upserted from the accounts array `transactions/sync` already returns, instead of a separate `accounts/get` round-trip — so metadata freshness is bounded by the sync schedule.
**Context**: .minerva/work/001-transactions-totals-and-nav-link (see git history if the worktree has been cleaned up)

## Context

When work unit 001 added the `accounts` table (to label per-account totals on
the transactions page), the obvious approach was to call Plaid's
`accounts/get` endpoint at sync time to fetch account metadata (name, mask,
type/subtype, balances).

Inspecting the Plaid SDK response confirmed that `transactions/sync` already
includes an `accounts` array on **every** paginated page, populated with the
same metadata `accounts/get` returns. Calling `accounts/get` would have been
a redundant extra round-trip per institution per sync.

## Finding

`PlaidClient.sync_transactions` collects accounts from the **last** non-empty
page of the paginated `transactions/sync` response and returns them alongside
`added/modified/removed/cursor`. `_sync_institution` upserts those into the
`Account` table by `plaid_account_id`. No separate `accounts/get` endpoint is
called.

Last non-empty page wins on purpose: Plaid populates the accounts array
opportunistically; the last page that has one has the freshest balance
snapshot.

## Implications

- Adding `accounts/get` later would be a regression unless something specific
  (e.g. account-only refresh without a sync) genuinely requires it.
- Account metadata is **only refreshed when a sync runs**. Metadata freshness
  is bounded by the sync schedule.
- If `transactions/sync` ever returns a page with an empty `accounts` array
  while a previous page populated it, the previous page's data is retained
  for this sync run. Empty-on-every-page would leave `Account` rows
  unchanged, which is the right default (don't blow away known accounts on
  an ambiguous response).
- **Balance freshness is handled separately.** As of work unit 003, balance
  fields are overwritten by a dedicated `/accounts/balance/get` call after
  the piggyback completes — the piggyback's balance values are treated as
  cached snapshots, not authoritative. See
  `002-decision-plaid-balance-refresh-via-dedicated-endpoint.md`.

## Related
- [[002-decision-plaid-balance-refresh-via-dedicated-endpoint]] — see also
- [[014-decision-plaid-liabilities-piggyback-on-sync]] — see also
- [[023-bug-transactions-sync-is-not-the-only-account-source]] — superseded in part by
  the piggyback is no longer the sole account feed; the no-`accounts/get` decision stands.
