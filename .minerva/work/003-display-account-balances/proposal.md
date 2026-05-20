# Proposal: display-account-balances

**Date**: 2026-05-20
**Status**: Shipped (2026-05-20)

## Goal

Show actual Plaid account balances on the transactions dashboard, sourced from a dedicated Plaid balance endpoint (`/accounts/balance/get`) so the figure shown is the authoritative real-time balance — not the in-filter transaction sum we used to render, and not the potentially-stale balance that came piggybacked on `transactions/sync`.

The filtered-period transaction sum is preserved as a secondary line so the filter UI still has signal without anyone mistaking the sum for a balance.

## Why

The user reported the "balances" on the dashboard are not correct. Before this work, the headline number in each totals-strip card was `sum(Transaction.amount)` for the current filter — neither labeled as a balance nor as a filtered total, so it visually read as a balance and disagreed with what the user saw in their bank app.

The `Account.current_balance` column existed (added in unit 001) but wasn't surfaced. Even if it had been, the value it stored came piggybacked on `transactions/sync`, which returns a *snapshot*: balance fields reflect whenever Plaid last refreshed the bank, not the live state. For a real-time number, Plaid's dedicated `/accounts/balance/get` endpoint is the authoritative source — see `.minerva/knowledge/002-decision-plaid-balance-refresh-via-dedicated-endpoint.md`.

## Approach (as shipped)

### 1. PlaidClient balance fetch — `app/plaid_client.py`

Added a `get_balances(access_token)` method that calls `accounts/balance/get` and returns the accounts array (each with `account_id` + `balances.current` / `.available` / `.iso_currency_code`).

### 2. Sync now refreshes balances — `app/sync.py`

`_sync_institution` calls `_refresh_balances(client, institution)` after the existing `_upsert_accounts(...)` step. `_refresh_balances` calls `client.get_balances(...)`, overwrites `current_balance` / `available_balance` / `iso_currency_code` / `last_synced_at` on each matching `Account` row, and returns `None` on success or an error string on failure.

If `get_balances` raises `plaid.ApiException`, the error is recorded on the `SyncLog.error` field but does **not** abort the sync — transactions still import, and the piggyback's snapshot balance is retained as a fallback. The institution's status is not flipped to `login_required` on a balance failure.

The piggyback approach from unit 001 still handles account metadata (name, mask, type, subtype). Only the balance fields are overwritten by the dedicated call. Knowledge entry 001 was amended to cross-reference the split.

### 3. Route returns `current_balance` — `app/routes.py`

`_account_totals` now selects `Account.current_balance` and `Account.iso_currency_code` alongside the existing aggregate columns, and groups by them. Filters (`institution`, `month`) are unchanged.

### 4. Template surfaces balance as the headline — `app/templates/index.html`

Each card is now shaped as:

- Institution name (small, muted)
- Account name + mask
- **Headline:** `current_balance` rendered with `"%.2f"` formatting, no leading sign, neutral color. If `current_balance` is `None`, the headline is an em-dash (`—`) — never `$0.00`, which would look like a real value.
- **Secondary line:** "This filter: ±$X.XX" using the existing red/green sign convention, paired with the transaction count.

Card `min-width` was bumped to 240px to accommodate the extra line.

### 5. Tests (all in the unit test suite, run via `pytest tests/`)

- `tests/test_plaid_client.py::test_get_balances` — pins the `accounts/balance/get` wrapper's return shape.
- `tests/test_sync.py::test_sync_refreshes_balances_via_balance_endpoint` — pins that the dedicated endpoint's live values overwrite the piggyback's snapshot values.
- `tests/test_sync.py::test_sync_handles_balance_endpoint_error` — pins that a Plaid `ApiException` on the balance endpoint is recorded on the `SyncLog` but does not abort the sync, leave the institution `login_required`, or drop transactions.
- `tests/test_routes.py::test_index_account_totals_include_current_balance` — pins `current_balance` in the route context.
- `tests/test_routes.py::test_index_account_card_renders_balance_and_filter_sum` — pins both the headline and secondary-line rendering.
- `tests/test_routes.py::test_index_account_card_renders_dash_when_balance_missing` — pins the em-dash placeholder for `None` balances.

The two pre-existing `test_sync_all_institutions_*` tests were updated to mock `get_balances` returning `[]` so they continue to exercise the integration path without asserting on balance values.

## Success criteria

- `Account.current_balance` is refreshed from Plaid's `/accounts/balance/get` endpoint on every sync (not just the `transactions/sync` piggyback). ✅
- A Plaid error from `/accounts/balance/get` is logged on the `SyncLog` row but does not abort the rest of the sync. ✅
- Each card in the dashboard's totals strip shows `Account.current_balance` as its headline, with the filtered-period transaction sum and txn count on a secondary line below. ✅
- Cards whose `current_balance` is `null` render an `—` placeholder for the balance (never `$0.00`). ✅
- `pytest` passes with no `--deselect`, and the new tests above are present. ✅ (74/74)

## Open Questions

_None._
