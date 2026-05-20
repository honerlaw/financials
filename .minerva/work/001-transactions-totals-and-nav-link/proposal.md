# Proposal: transactions-totals-and-nav-link

**Date**: 2026-05-20
**Status**: Shipped (2026-05-20)

## Goal

Two small additions to the transactions UI:

1. Add a **Transactions** link in the top navbar (next to the existing **Chat** link) that navigates to `/` — the transactions list / dashboard.
2. On the transactions page (`/`), render a **per-account totals strip at the top**, showing one entry per (institution, account) within the current filter, displaying institution name, account name (with mask if available), and the total of in-filter transaction amounts.

## Why

- The only existing way to navigate back to the transactions page from `/chat` was the "Financials" brand text in the navbar, which is not visually obvious as a navigation control. A labeled `Transactions` link makes both top-level destinations symmetrical with **Chat**.
- The transactions page used to list every line item but provided no aggregate orientation. The single user wants to glance at the page and see how much they've spent on each card before scanning the line items below. A per-(institution, account) total at the top answers that immediately.

## Decisions (folded from open questions, 2026-05-20)

- **Total semantics:** filtered sum (matches the table below). `current_balance` is still stored on the `accounts` row so a future iteration can surface it as a secondary metric without further schema changes.
- **Sign convention:** keep parity with the existing table — positive = outflow (red), negative = inflow (green). No extra "Spent" / "Net" label; the existing color convention reads cleanly.
- **Brand link:** keep the "Financials" brand text clickable. The explicit "Transactions" link is the new primary affordance; the brand link is preserved so existing muscle memory still works.

## Approach (as shipped)

### 1. Navbar link — `app/templates/base.html`

A `<a href="/">Transactions</a>` link was added immediately to the left of the existing `Chat` link in the navbar. Brand text remains a link to `/` as well.

Resulting nav order: `Financials` (brand) | **Transactions** | **Chat** | sync label | Sync now | ⚙

### 2. Account model — `app/models.py`

Added an `Account` table to give per-account totals a name, mask, and stable identity:

| column                | type                          | notes                                   |
|-----------------------|-------------------------------|-----------------------------------------|
| id                    | Integer PK                    |                                         |
| institution_id        | FK → institutions.id, cascade |                                         |
| plaid_account_id      | String, unique                | matches `Transaction.account_id` string |
| name                  | String                        | Plaid `account.name`                    |
| official_name         | String, nullable              | Plaid `account.official_name`           |
| mask                  | String(8), nullable           | last 4 of account number                |
| type                  | String, nullable              | depository / credit / loan / investment |
| subtype               | String, nullable              | checking / savings / credit card / …    |
| current_balance       | Numeric(12,2), nullable       | Plaid `balances.current`                |
| available_balance     | Numeric(12,2), nullable       | Plaid `balances.available`              |
| iso_currency_code     | String(10), nullable          |                                         |
| last_synced_at        | DateTime(tz), nullable        | updated each sync                       |
| created_at            | DateTime(tz)                  |                                         |

Relationship: `Institution.accounts` (lazy=True, cascade='all, delete-orphan').

`Transaction.account_id` (already a String column holding the Plaid account id) was **not** replaced by a foreign key — keeping it as-is avoided touching the existing column. The join is cheap (`Account.plaid_account_id == Transaction.account_id` within the same `institution_id`).

### 3. Migration

Alembic migration `8b3e1a7c9d42_add_accounts_table.py` creates the `accounts` table (`Revises: 2a1f9c7e5d3b`).

### 4. Sync integration — `app/sync.py` + `app/plaid_client.py`

`PlaidClient.sync_transactions` was extended to also return the accounts payload that `transactions/sync` already includes on every page; `_sync_institution` upserts those into the `accounts` table by `plaid_account_id`, refreshing name / mask / type / subtype / balances / `last_synced_at` on every sync.

No new Plaid endpoint was added — see [.minerva/knowledge/001-decision-plaid-accounts-piggyback-on-sync.md][k001] for why piggybacking on `transactions/sync` beat calling `accounts/get`.

[k001]: ../../knowledge/001-decision-plaid-accounts-piggyback-on-sync.md

### 5. Transactions route — `app/routes.py`

`index()` was refactored to extract month-bound parsing into a `_month_bounds()` helper (used by both the table query and the totals query), and a second helper `_account_totals(institution_id, month_start, month_end)` builds a per-(institution, account) aggregate via an outer join from `Account` → `Transaction`. The outer join means accounts with zero in-filter transactions still render with `$0.00`; filtering by `institution` hides accounts from other institutions.

### 6. Template — `app/templates/index.html`

Horizontally-scrollable card strip rendered above the filter row (`d-flex gap-2 mb-3 overflow-auto pb-1`). Each card (`min-width: 220px`) shows institution name (small, muted), account name + mask, total (large, colored via the table's red/green convention), and transaction count.

### 7. Tests

Added/updated tests:

- `tests/test_plaid_client.py::test_sync_transactions_handles_pagination` — updated to unpack the 5-tuple return shape and assert the accounts array from the final page wins.
- `tests/test_sync.py::test_sync_all_institutions_happy_path` — updated to mock the 5-tuple return shape.
- `tests/test_sync.py::test_upsert_accounts_inserts_new_rows` — pins `_upsert_accounts` insertion of name / mask / type / subtype / balances.
- `tests/test_sync.py::test_upsert_accounts_updates_balances_on_second_call` — pins balance refresh on subsequent sync.
- `tests/test_sync.py::test_sync_all_institutions_persists_accounts` — pins integration of upsert into the sync path.
- `tests/test_routes.py::test_index_navbar_has_transactions_link` — pins the navbar link rendering.
- `tests/test_routes.py::test_index_account_totals_aggregate_by_account` — pins per-account total + mask rendering.
- `tests/test_routes.py::test_index_account_totals_respect_month_filter` — pins month-filter consistency.
- `tests/test_routes.py::test_index_account_totals_hide_other_institutions_when_filtered` — pins institution-filter scoping.
- `tests/test_routes.py::test_index_account_totals_include_zero_txn_accounts` — pins that a freshly-linked account renders with `$0.00` and `0 txns` even when no in-filter transactions exist (added in the review pass).

## Success criteria

- A **Transactions** link is visible in the top navbar, sits next to the **Chat** link, and clicking it navigates to `/`. ✅
- The `/` page renders a per-account totals strip above the filter controls. Each entry shows institution name, account name, mask (if any), and total of in-filter transaction amounts. ✅
- The totals strip respects the existing `institution` and `month` query-string filters, and updates consistently when filters change. ✅
- Running a sync against an already-linked institution populates the `accounts` table (no manual backfill steps required from the user). ✅
- `pytest` passes, including new tests covering the route context and sync-side account upsert. ✅ (66/66; 1 deselected = pre-existing failure on `main`, see `followups.md`)

## Open Questions

_None._
