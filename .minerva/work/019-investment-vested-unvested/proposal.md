# Proposal: investment-vested-unvested

**Date**: 2026-08-23
**Status**: Draft

## Goal

Surface **vested** and **unvested** equity-compensation value on each investment
account's dashboard card, sourced from Plaid's `/investments/holdings/get`, so a
linked stock-plan account (E*TRADE) shows what is actually vested rather than a
single undifferentiated balance.

## Why

Reported symptom: the linked E*TRADE account shows no vested/unvested split on
the dashboard. It cannot — the app has never touched Plaid's `investments`
product. `transactions/sync` returns the account and its balance; nothing else.

Plaid does expose the numbers. Each `Holding` in
`/investments/holdings/get` carries `vested_quantity` and `vested_value`
alongside `institution_value` — populated for equity holdings at institutions
that report equity compensation. Unvested value is the remainder,
`institution_value - vested_value`, for those same holdings.

This is the third instance of one established shape in this repo: a dedicated
Plaid endpoint called after the transaction sync, writing nullable columns onto
`Account`, non-fatally. Balances did it in
[[002-decision-plaid-balance-refresh-via-dedicated-endpoint]]; liability due
dates did it in [[014-decision-plaid-liabilities-piggyback-on-sync]]. This unit
follows the same shape rather than inventing a new one.

## Approach

### 1. Schema — `app/models.py` + a migration

Two nullable columns on `Account`:

- `vested_value` (Numeric 12,2) — summed vested value across the account's
  equity-comp holdings.
- `unvested_value` (Numeric 12,2) — summed `institution_value - vested_value`
  across those same holdings.

Both null for every account with no equity-comp holdings — depository accounts,
plain brokerage accounts, and any Item not consented to `investments`. That is
the same null-means-not-applicable contract the liability columns already use.

### 2. Plaid consent + fetch — `app/plaid_client.py`

- `investments` joins `liabilities` in `additional_consented_products` on both
  `create_link_token` and `create_update_link_token`. Consented, **not**
  required — making it required would break linking at institutions that have
  no investment accounts.
- New `get_investment_holdings(access_token)` wraps
  `/investments/holdings/get` and returns the response's `holdings` list.

### 3. Sync — `app/sync.py`

`_refresh_investments(client, institution)` runs after `_refresh_liabilities`,
with the identical non-fatal contract: a `plaid.ApiException` never aborts the
sync, unexpected codes are joined onto `SyncLog.error`, and the benign set
(`ADDITIONAL_CONSENT_REQUIRED`, `PRODUCTS_NOT_SUPPORTED`,
`NO_INVESTMENT_ACCOUNTS`, `NO_ACCOUNTS`) is a silent no-op.

Aggregation, per account:

- Only holdings whose vested value is *known* participate. A plain brokerage
  holding reports `vested_value = None` and must not be counted as unvested —
  it is not unvested, it is not equity comp.
- `vested_value` is used directly when present; when it is null but
  `vested_quantity` is not, it is derived as
  `vested_quantity * institution_price`. (Same spirit as the mortgage
  `next_monthly_payment` fallback already in `_refresh_liabilities`.)
- `unvested = max(institution_value - vested, 0)` — clamped, because a stale
  `institution_price` can otherwise produce a negative remainder.
- An account whose holdings all report no vested figure keeps both columns
  null, so its card is unchanged.

### 4. Dashboard — `app/routes.py` + `app/templates/index.html`

`_account_totals` selects and groups the two new columns. The card gains one
row, rendered only when either value is non-null, directly mirroring the
existing due-date/balance-due row:

```
Vested $12,345.67        Unvested $8,900.00
```

### 5. Tests — `tests/test_plaid_client.py`, `tests/test_sync.py`, `tests/test_routes.py`

Mirroring the liability tests already in place: the client method issues the
request, sync populates both columns, the `vested_quantity` fallback works,
non-equity holdings are ignored, benign error codes stay off the SyncLog, an
unexpected code lands on it non-fatally, and the dashboard renders the row.

### Rejected alternatives

- **Full `Holding` / `Security` tables with a per-lot holdings view.** Correct
  destination if the app ever grows a portfolio page, but it is a new subsystem
  — two tables, a sync reconciliation path, and a new view — for a request that
  asks only for two numbers per account. Deferred as a follow-up.
- **Call `/investments/holdings/get` at dashboard render time.** No migration,
  always live, but it puts a network round-trip per institution on every page
  load and breaks the piggyback rule from
  [[001-decision-plaid-accounts-piggyback-on-sync]].
- **Store only `vested_value` and derive unvested in the template from
  `current_balance`.** One less column, but wrong: an investment account's
  current balance includes cash and non-equity positions, so the remainder is
  not the unvested figure.

## Success criteria

1. `Account` has nullable `vested_value` and `unvested_value` columns, added by
   a migration that upgrades and downgrades cleanly.
2. `create_link_token` and `create_update_link_token` both consent to
   `investments` alongside `liabilities`.
3. `PlaidClient.get_investment_holdings` calls `/investments/holdings/get` and
   returns the holdings list.
4. A sync populates both columns for an account with equity-comp holdings, and
   leaves them null for an account whose holdings report no vested figure.
5. `ADDITIONAL_CONSENT_REQUIRED`, `PRODUCTS_NOT_SUPPORTED`,
   `NO_INVESTMENT_ACCOUNTS`, and `NO_ACCOUNTS` from the holdings call leave
   `SyncLog.error` untouched; an unexpected code is recorded there without
   aborting the sync.
6. The dashboard account card shows a Vested / Unvested row when either value
   is present, and is visually unchanged when both are null.
7. `pytest` passes.

## Open Questions

**The existing E*TRADE Item will stay blank until it is re-connected.** Per
[[015-decision-liability-consent-requires-update-mode]], Plaid consent is fixed
at link time: adding `investments` to `additional_consented_products` only
affects Items linked afterwards. Every already-linked Item returns
`ADDITIONAL_CONSENT_REQUIRED` until the user hits "Re-connect" in `/settings`,
which is exactly the migration step that entry says to budget for. There is no
server-side way to grant it.

Whether Plaid actually returns `vested_value` for this specific E*TRADE stock
plan account cannot be verified from here — it depends on what the institution
reports. If it comes back null, the columns stay null and the card is
unchanged; the remedy would be a holdings-level view, not a change to this
shape.
