# Vested / unvested equity comp comes from `/investments/holdings/get`, aggregated onto `Account`

**Date**: 2026-08-23
**Type**: decision
**Summary**: Vested and unvested equity-compensation totals come from a dedicated `/investments/holdings/get` call after the liability refresh, aggregated per account into two nullable `Account` columns, non-fatally.
**Context**: .minerva/work/019-investment-vested-unvested (see git history if the worktree has been cleaned up)

## Context

A linked E*TRADE stock-plan account showed a single balance on the dashboard
and no vested/unvested split. It could not: the app had never touched Plaid's
`investments` product, so the only account data it had was what
`transactions/sync` returns.

Plaid does report the figures. Each `Holding` from `/investments/holdings/get`
carries `vested_quantity` / `vested_value` alongside `institution_value`,
populated for equity holdings at institutions that track equity compensation.

## Finding

- `PlaidClient.get_investment_holdings(access_token)` wraps
  `/investments/holdings/get` and returns the response's `holdings` list. Each
  holding ties back to an `Account` by `account_id`.
- `Account` gained two nullable columns (migration `e9c2b7d41a58`):
  `vested_value`, `unvested_value`.
- `_sync_institution` calls `_refresh_investments(...)` after
  `_refresh_liabilities(...)` — the third instance of the same shape (see
  [[002-decision-plaid-balance-refresh-via-dedicated-endpoint]] and
  [[014-decision-plaid-liabilities-piggyback-on-sync]]).
- **Only holdings with a known vested figure participate.** `vested_value` is
  used when present; when null but `vested_quantity` is not, the vested amount
  is derived as `vested_quantity * institution_price` and rounded to cents.
  A holding reporting neither is skipped **entirely** — it contributes to
  neither total. A plain brokerage position is not unvested equity, and
  counting it as such would report a fictitious vesting schedule.
- **Unvested is the clamped remainder**, `max(institution_value - vested, 0)`.
  Plaid has no unvested field; a stale `institution_price` can otherwise price
  a holding below its own vested portion and produce a negative remainder. A
  holding with no `institution_value` contributes nothing to the unvested
  total — the remainder is unknown, not zero.
- `investments` joins `liabilities` in `additional_consented_products` on both
  `create_link_token` and `create_update_link_token`. Consented, not required,
  for the same reason liabilities is: a required product breaks linking at
  institutions that cannot serve it.

## Implications

- **Every already-linked Item must be re-connected before this shows anything.**
  This is [[015-decision-liability-consent-requires-update-mode]] applying
  verbatim to a second product, exactly as that entry predicted: consent is
  fixed at link time, so existing Items return `ADDITIONAL_CONSENT_REQUIRED`
  until the user hits "Re-connect" in `/settings`. There is no server-side way
  to grant it. `_BENIGN_INVESTMENT_ERROR_CODES` therefore includes that code
  from the start rather than after a log full of noise.
- **Null means "not equity comp", and the card renders nothing** — never a $0
  vested balance, which would read as "nothing has vested" rather than "this
  account has no vesting schedule".
- **Totals are rounded to cents on write** (`_money`), because Postgres rounds
  a `Numeric(12, 2)` insert and SQLite — which the test suite runs on — does
  not. Without it the derived-value path reads back differently per
  environment.
- **The columns are never cleared.** Only accounts present in the current
  holdings payload are written, so an account that stops reporting equity comp
  keeps its last values. `_refresh_liabilities` has the identical behavior;
  filed as a follow-up rather than diverged from.

## Related

- [[014-decision-plaid-liabilities-piggyback-on-sync]] — builds on
  the liability refresh this mirrors — same post-sync, dedicated-endpoint, non-fatal, nullable-columns-on-`Account` shape.
- [[015-decision-liability-consent-requires-update-mode]] — builds on
  the consent constraint, which applies unchanged to this second consented product.
- [[002-decision-plaid-balance-refresh-via-dedicated-endpoint]] — see also
  the original dedicated-endpoint refresh the shape descends from.
- [[017-pattern-migration-chain-is-postgres-only]] — see also
  how migration `e9c2b7d41a58` was verified without a Postgres.
