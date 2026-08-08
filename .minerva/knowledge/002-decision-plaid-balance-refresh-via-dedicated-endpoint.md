# Plaid `transactions/sync` returns cached balances — `/accounts/balance/get` is the authoritative real-time source

**Date**: 2026-05-20
**Type**: decision
**Summary**: Balances carried by `transactions/sync` are cached snapshots; a dedicated `/accounts/balance/get` call after each sync overwrites them with authoritative real-time values.
**Context**: .minerva/work/003-display-account-balances (see git history if the worktree has been cleaned up)

## Context

Work unit 001 added the `accounts` table and populated `current_balance` /
`available_balance` from the accounts payload that Plaid's `transactions/sync`
endpoint already returns on every page (the "piggyback" approach — see
`001-decision-plaid-accounts-piggyback-on-sync.md`). Those fields were stored
but not displayed.

When unit 003 surfaced those values on the dashboard, the user reported the
"balances" were wrong. The root cause is that the balance fields in
`transactions/sync`'s accounts payload are a **cached snapshot** — they
reflect whenever Plaid last polled the institution, not the live state of
the account. For a dashboard headline labelled "balance", that's not good
enough.

Plaid's `/accounts/balance/get` endpoint exists precisely for this case:
calling it forces Plaid to fetch live balances from the institution.

## Finding

`PlaidClient.get_balances(access_token)` (added in unit 003) wraps
`/accounts/balance/get`. `_sync_institution` calls it after the existing
`_upsert_accounts(...)` piggyback step and overwrites the just-written
balance fields with the live values:

```python
balance_error = _refresh_balances(client, institution)
if balance_error:
    log.error = balance_error
```

`_refresh_balances` swallows `plaid.ApiException` and surfaces it on the
`SyncLog` row — a balance-endpoint failure annotates the log but does not
abort the sync, because the piggyback has already written something
non-empty.

## Implications

- **Metadata vs. balance is split.** Account metadata (name, mask, type,
  subtype) still comes from the piggyback — no behavior change there. Only
  the balance fields are overwritten by `/accounts/balance/get`. Knowledge
  entry 001's recommendation against `accounts/get` is unchanged.
- **Each sync now makes one extra Plaid call per institution.** This is the
  cost of authoritative balances. Worth it for the dashboard headline; if
  rate limits become a problem on a larger Plaid plan, a "skip balance
  refresh on this sync" knob would be the right next step rather than
  reverting to piggyback-only.
- **Balance-refresh errors are non-fatal.** Future sync changes must preserve
  this — if a Plaid balance call hard-fails the sync, transactions stop
  importing, which is a much worse user-visible regression than slightly
  stale balances.
- **The cached vs. live distinction is a Plaid constraint, not a quirk of
  our integration.** Any future "what's the latest balance" use case must
  call `/accounts/balance/get` directly; reading `Account.current_balance`
  only returns the freshest value we've written, which is bounded by sync
  cadence.

## Related

- [[001-decision-plaid-accounts-piggyback-on-sync]] — builds on
  the piggybacked accounts payload whose cached balances this refresh overwrites.
- [[010-decision-budget-alert-notifier]] — see also
- [[014-decision-plaid-liabilities-piggyback-on-sync]] — see also
- [[016-decision-daily-digest-notifier]] — see also
