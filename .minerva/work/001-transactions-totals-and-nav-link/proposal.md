# Proposal: transactions-totals-and-nav-link

**Date**: 2026-05-20
**Status**: Draft

## Goal

Two small additions to the transactions UI:

1. Add a **Transactions** link in the top navbar (next to the existing **Chat** link) that navigates to `/` — the transactions list / dashboard.
2. On the transactions page (`/`), render a **per-account totals strip at the top**, showing one entry per (institution, account) within the current filter, displaying institution name, account name (with mask if available), and the total of in-filter transaction amounts.

## Why

- The only existing way to navigate back to the transactions page from `/chat` is the "Financials" brand text in the navbar, which is not visually obvious as a navigation control. A labeled `Transactions` link makes both top-level destinations symmetrical with **Chat**.
- The transactions page currently lists every line item but provides no aggregate orientation. The single user wants to glance at the page and see how much they've spent on each card before scanning the line items below. A per-(institution, account) total at the top answers that immediately.

## Approach

### 1. Navbar link — `app/templates/base.html`

Add a `Transactions` link immediately to the left of the existing `Chat` link in the navbar. Brand text remains a link to `/` as well; the explicit label is the primary affordance.

Resulting nav order: `Financials` (brand) | **Transactions** | **Chat** | sync label | Sync now | ⚙

### 2. Account model — `app/models.py`

Add an `Account` table to give per-account totals a name, mask, and stable identity:

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

`Transaction.account_id` (already a String column holding the Plaid account id) is **not** replaced by a foreign key — keeping it as-is avoids touching the existing column and the join is cheap (`Account.plaid_account_id == Transaction.account_id` within the same `institution_id`).

### 3. Migration

Add an Alembic migration creating the `accounts` table.

### 4. Sync integration — `app/sync.py` + `app/plaid_client.py`

The Plaid `transactions/sync` response already includes an `accounts` array on every call. Extend `PlaidClient.sync_transactions` to also return that array, and in `_sync_institution` upsert each entry into the `accounts` table by `plaid_account_id` (update name / mask / balances / `last_synced_at` on every sync; insert if missing).

No new Plaid endpoint is required — this piggybacks on the existing sync path, so existing institutions get backfilled automatically on the next scheduled sync (or via the existing "Sync now" button).

### 5. Transactions route — `app/routes.py`

In the `index` view, after building the filtered `Transaction` query, run a second aggregate query joined to `Account`:

```python
totals = (
    db.session.query(
        Account.id, Account.name, Account.mask,
        Institution.id.label('institution_id'), Institution.name.label('institution_name'),
        db.func.coalesce(db.func.sum(Transaction.amount), 0).label('total'),
        db.func.count(Transaction.id).label('txn_count'),
    )
    .join(Institution, Institution.id == Account.institution_id)
    .outerjoin(Transaction, db.and_(
        Transaction.account_id == Account.plaid_account_id,
        Transaction.institution_id == Account.institution_id,
        Transaction.removed == False,
        # plus the same institution_id / month filters applied to the table query
    ))
    .group_by(Account.id, Institution.id)
    .order_by(Institution.name, Account.name)
    .all()
)
```

Apply the same `institution_id` and `month` filters used for the main transaction query so the strip and table stay consistent. Accounts with zero in-filter transactions are still rendered (so a freshly-linked account shows up with `$0.00`), but if a single institution is filtered, accounts from other institutions are hidden.

Pass `account_totals` to the template.

### 6. Template — `app/templates/index.html`

Render a horizontally-scrollable card strip above the filter row. Each card shows:

- Institution name (small, muted)
- Account name + mask (`Sapphire Preferred ····1234`)
- Total (large; same red/green color convention used in the table — positive = outflow = red, negative = inflow = green)
- Transaction count (small, muted)

Layout: Bootstrap `d-flex gap-2 overflow-auto pb-2` row of `card`s, each `min-width: 220px`. The strip honors the current filter, so changing institution / month updates which cards appear and their totals.

### 7. Tests

- Unit test in `tests/test_routes.py`: `GET /` with seeded accounts + transactions returns the expected `account_totals` context, filtered correctly by `institution` and `month` query params.
- Unit test in `tests/test_sync.py`: a `transactions_sync` response containing `accounts` upserts `Account` rows and updates balances on a second call.

## Success criteria

- A **Transactions** link is visible in the top navbar, sits next to the **Chat** link, and clicking it navigates to `/`.
- The `/` page renders a per-account totals strip above the filter controls. Each entry shows institution name, account name, mask (if any), and total of in-filter transaction amounts.
- The totals strip respects the existing `institution` and `month` query-string filters, and updates consistently when filters change.
- Running a sync against an already-linked institution populates the `accounts` table (no manual backfill steps required from the user).
- `pytest` passes, including new tests covering the route context and sync-side account upsert.

## Decisions (folded from open questions, 2026-05-20)

- **Total semantics:** filtered sum (matches the table below). `current_balance` is still stored on the `accounts` row so a future iteration can surface it as a secondary metric without further schema changes.
- **Sign convention:** keep parity with the existing table — positive = outflow (red), negative = inflow (green). No extra "Spent" / "Net" label; the existing color convention reads cleanly.
- **Brand link:** keep the "Financials" brand text clickable. The explicit "Transactions" link is the new primary affordance; the brand link is preserved so existing muscle memory still works.

## Open Questions

_None._
