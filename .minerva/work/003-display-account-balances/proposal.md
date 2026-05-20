# Proposal: display-account-balances

**Date**: 2026-05-20
**Status**: Draft

## Goal

Show actual Plaid account balances on the transactions dashboard, sourced from a dedicated Plaid balance endpoint (`/accounts/balance/get`) so the figure shown is the authoritative real-time balance — not the in-filter transaction sum we render today, and not the potentially-stale balance that came piggybacked on `transactions/sync`.

Also keep the existing filtered-period transaction sum visible, but demoted to a secondary line so the filter UI still has signal without anyone mistaking the sum for a balance.

## Why

The user reported the "balances" on the dashboard are not correct. Today the headline number in each totals-strip card is `sum(Transaction.amount)` for the current filter — clearly labeled neither as a balance nor as a filtered total, so it visually reads as a balance and disagrees with what the user sees in their actual bank app.

The `Account.current_balance` column exists (added in unit 001) and is populated as a side-effect of `transactions/sync`'s accounts payload. Two problems with relying on that:

1. **It isn't displayed.** The dashboard never reads it.
2. **It may be stale.** Plaid's `transactions/sync` returns the institution's accounts as a *snapshot*; the balance fields reflect whenever Plaid last refreshed the bank. For a real-time number, Plaid's dedicated `/accounts/balance/get` endpoint is the canonical source — it forces a fresh pull from the institution.

The user explicitly asked for the balance to come "directly from the account plaid api". `/accounts/balance/get` is that API.

## Approach

### 1. Add a Plaid balance fetch — `app/plaid_client.py`

Add a `get_balances(access_token)` method on `PlaidClient` that calls `accounts/balance/get` and returns the accounts array (each entry having `account_id` + `balances.current` / `.available` / `.iso_currency_code`).

```python
from plaid.model.accounts_balance_get_request import AccountsBalanceGetRequest

def get_balances(self, access_token):
    response = self._client.accounts_balance_get(
        AccountsBalanceGetRequest(access_token=access_token)
    )
    return response.accounts
```

### 2. Refresh balances on every sync — `app/sync.py`

In `_sync_institution`, after the existing `_upsert_accounts(institution.id, accounts)` call (which still handles metadata via the `transactions/sync` piggyback for name / mask / type / subtype), call `client.get_balances(institution.access_token)` and write the fresh balances into the matching `Account` rows by `plaid_account_id`.

Failure handling: if `get_balances` raises `plaid.ApiException`, log it on the existing `SyncLog` row but **do not** fail the whole sync — the transactions piggyback already populated something useful, and the dashboard's worst case is a slightly-stale balance.

This **extends** rather than replaces the piggyback approach from `.minerva/knowledge/001-decision-plaid-accounts-piggyback-on-sync.md`:
- Metadata (name, mask, type, subtype) → piggyback (no extra call).
- Balances → dedicated `/accounts/balance/get` call (one extra call per institution per sync).

Knowledge entry 001 will be updated by `minerva:promote` to reflect this split.

### 3. Surface balance in the route — `app/routes.py`

Extend `_account_totals` to include `Account.current_balance` and `Account.iso_currency_code` in its result rows. The aggregation keys / filters stay the same — the balance is per account, not per filter window.

### 4. Update the totals strip — `app/templates/index.html`

Reshape each card so the headline is the balance and the filtered transaction sum is a secondary line:

```
Institution
Account name ····mask
$1,234.56                    ← Account.current_balance (large, neutral color)
This filter: -$45.67 · 4 txns  ← filtered sum + count (small, muted, red/green by sign)
```

Sign convention rules for the **headline balance** (different from the filtered total):
- For **credit** accounts (`account.type == 'credit'`), Plaid returns balances as positive numbers representing what is owed. Display as a positive number with no leading +/−.
- For **depository** accounts, Plaid returns positive numbers for what is held. Display as positive.
- For accounts where balance is `None` (Plaid didn't return one — possible on investment accounts or during a partial refresh), render an `—` placeholder, not `$0.00`.

The filtered-sum secondary line keeps the existing color convention (positive = outflow, red; negative = inflow, green; zero = muted).

### 5. Tests

- `tests/test_plaid_client.py::test_get_balances` — pins the new method's wrapper-and-return shape.
- `tests/test_sync.py::test_sync_refreshes_balances_via_balance_endpoint` — pins that `_sync_institution` calls `get_balances` and writes the result into `Account.current_balance` / `Account.available_balance`.
- `tests/test_sync.py::test_sync_handles_balance_endpoint_error` — pins that a Plaid error on `get_balances` is logged but doesn't fail the sync.
- `tests/test_routes.py::test_index_account_totals_include_current_balance` — pins `current_balance` in the route context.
- `tests/test_routes.py::test_index_account_card_renders_balance_and_filter_sum` — pins both lines render with the balance as the headline.
- `tests/test_routes.py::test_index_account_card_renders_dash_when_balance_missing` — pins the `—` placeholder.

## Success criteria

- `Account.current_balance` is refreshed from Plaid's `/accounts/balance/get` endpoint on every sync (not just the `transactions/sync` piggyback).
- A Plaid error from `/accounts/balance/get` is logged on the `SyncLog` row but does not abort the rest of the sync.
- Each card in the dashboard's totals strip shows `Account.current_balance` as its headline, with the filtered-period transaction sum and txn count on a secondary line below.
- Cards whose `current_balance` is `null` render an `—` placeholder for the balance (never `$0.00`).
- `pytest` passes with no `--deselect`, and the new tests above are present.

## Open Questions

_None._
