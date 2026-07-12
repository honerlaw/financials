# Proposal: account-due-date-and-balance

**Date**: 2026-07-12
**Status**: Shipped (2026-07-12)

## Goal

Show the upcoming payment **due date** and **balance due** for each account on
the main dashboard, so credit-card and loan accounts surface when a payment is
owed and how much — right alongside the existing current-balance headline.

## Why

The dashboard's account cards already show each account's current balance (unit
003) and the in-filter transaction sum. For a liability account (credit card,
student loan, mortgage) the number that actually drives action is *when the
next payment is due* and *how much is owed on the statement* — neither of which
is derivable from transactions or the account balance. Plaid exposes these via
its dedicated `/liabilities/get` endpoint.

## Approach (as shipped)

### 1. Schema — `app/models.py` + migration `c4e8b2f6a1d9`

Three nullable columns added to `Account`:

- `next_payment_due_date` (Date) — "Due date"
- `last_statement_balance` (Numeric 12,2) — "Balance due" (the statement balance owed)
- `minimum_payment_amount` (Numeric 12,2) — the minimum payment, shown as a secondary hint

All nullable: depository accounts (and any Item not consented to the
`liabilities` product) simply leave them null.

### 2. Plaid consent + fetch — `app/plaid_client.py`

- `create_link_token` now passes `additional_consented_products=[Products('liabilities')]`.
  `liabilities` is *consented but not required* — institutions that don't
  support it still link (transactions stays the only required product), and
  when present we can call `/liabilities/get`.
- New `get_liabilities(access_token)` wraps `/liabilities/get` and returns the
  `liabilities` object (`.credit`, `.student`, `.mortgage` arrays).

### 3. Sync populates the fields — `app/sync.py`

`_sync_institution` calls `_refresh_liabilities(client, institution)` after the
existing `_refresh_balances(...)` step. It maps each liability entry to its
`Account` row by `account_id` and writes the due date, statement balance, and
minimum payment. Mortgages have no `minimum_payment_amount`; the amount owed
lives on `next_monthly_payment`, which the refresh falls back to.

Like balance refresh, liability refresh is **non-fatal**: a Plaid
`ApiException` never aborts the sync. Errors from balance *and* liability
refresh are accumulated and joined onto `SyncLog.error`. The common "this Item
has no liabilities" responses (`PRODUCTS_NOT_SUPPORTED`, `NO_LIABILITY_ACCOUNTS`,
`NO_ACCOUNTS`) are treated as benign no-ops — every Item linked before this
feature is non-consented, so annotating the log for them would be pure noise.

See `.minerva/knowledge/014-decision-plaid-liabilities-piggyback-on-sync.md`.

### 4. Route — `app/routes.py`

`_account_totals` selects and groups by the three new columns. `index` passes
`today` to the template for the overdue check.

### 5. Template — `app/templates/index.html`

Each card gains a due-date / balance-due line, rendered only when the account
has liability data (`next_payment_due_date` or `last_statement_balance` set):

- Left: `Due {Mon D}` (muted) or `Overdue {Mon D}` (red, bold) when the due
  date is before `today`.
- Right: the statement balance (falls back to the minimum payment, then `—`).
- A subtle `min $X.XX due` sub-line when both a statement balance and a minimum
  payment are present.

Depository cards are visually unchanged.

### 6. Tests

- `tests/test_plaid_client.py::test_get_liabilities` — pins the wrapper's shape.
- `tests/test_plaid_client.py::test_create_link_token` — asserts `liabilities`
  is in `additional_consented_products`.
- `tests/test_sync.py::test_sync_populates_liability_fields` — credit fields land.
- `tests/test_sync.py::test_refresh_liabilities_uses_next_monthly_payment_for_mortgage`
  — mortgage fallback to `next_monthly_payment`.
- `tests/test_sync.py::test_sync_ignores_benign_liability_error` — benign codes
  are not annotated on the SyncLog.
- `tests/test_sync.py::test_sync_logs_unexpected_liability_error` — an
  unexpected code is recorded, non-fatally.
- `tests/test_routes.py` — liability fields in the route context; card renders
  the due date, balance due, and min hint; overdue styling; and the line is
  omitted for accounts without liability data.

## Success criteria

- `Account` stores due date, statement balance, and minimum payment, refreshed
  from `/liabilities/get` on every sync. ✅
- A liability-endpoint failure is non-fatal and does not abort the sync;
  benign "no liabilities" responses don't annotate the SyncLog. ✅
- Each liability card shows the due date and balance due; overdue payments are
  visually flagged. ✅
- Depository cards render unchanged. ✅
- `pytest` passes with no `--deselect`. ✅ (191/191)

## Open Questions

- Existing Items linked before this change were never consented to the
  `liabilities` product, so their `/liabilities/get` calls return
  `PRODUCTS_NOT_SUPPORTED` (silently ignored) and their liability fields stay
  null until the user re-links / re-consents via update mode. A future
  follow-up could trigger update-mode consent for existing credit accounts.
