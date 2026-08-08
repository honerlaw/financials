# Liability due dates & balances come from `/liabilities/get`, refreshed on sync, non-fatally

**Date**: 2026-07-12
**Type**: decision
**Context**: .minerva/work/014-account-due-date-and-balance (see git history if the worktree has been cleaned up)

## Context

The dashboard account cards needed to show each account's upcoming payment
**due date** and **balance due**. Neither is derivable from transactions or the
account balance — they are liability attributes Plaid exposes only through its
dedicated `/liabilities/get` endpoint (analogous to how live balances come from
`/accounts/balance/get`, see entry 002).

## Finding

- `PlaidClient.get_liabilities(access_token)` wraps `/liabilities/get` and
  returns the `liabilities` object with `.credit`, `.student`, `.mortgage`
  arrays. Each entry ties back to an `Account` by `account_id`.
- `Account` gained three nullable columns (migration `c4e8b2f6a1d9`):
  `next_payment_due_date`, `last_statement_balance`, `minimum_payment_amount`.
- `_sync_institution` calls `_refresh_liabilities(...)` after
  `_refresh_balances(...)`. It writes the due date and statement/minimum amounts
  onto each matching `Account` row. Mortgages have no `minimum_payment_amount`,
  so the amount owed falls back to `next_monthly_payment`.
- **`liabilities` is consented, not required.** `create_link_token` passes
  `additional_consented_products=[Products('liabilities')]`. Making it a
  *required* product would break linking at institutions that don't support
  liabilities; as an additional consented product, transactions stays the only
  required product and liabilities is used opportunistically when available.

## Implications

- **Liability refresh is non-fatal** (mirrors the `_refresh_balances`
  contract). A `plaid.ApiException` from `/liabilities/get` never aborts the
  sync — transactions must keep importing. Balance and liability errors are
  accumulated and joined onto `SyncLog.error`.
- **"No liabilities" is normal, not an error.** `ADDITIONAL_CONSENT_REQUIRED`,
  `PRODUCTS_NOT_SUPPORTED`, `NO_LIABILITY_ACCOUNTS`, and `NO_ACCOUNTS` are
  treated as benign no-ops and
  are *not* written to the SyncLog. This matters because **every Item linked
  before this feature was never consented to `liabilities`**, so their calls
  return `ADDITIONAL_CONSENT_REQUIRED` on every sync — annotating the log for
  them would bury real errors in noise. Their liability fields stay null until
  the user re-consents via update mode. (This entry originally named
  `PRODUCTS_NOT_SUPPORTED` as that code; it was wrong, and the miss let the
  real code through to the log — corrected in
  [[015-decision-liability-consent-requires-update-mode]], which also records
  how the consent is actually granted.)
- **Freshness is bounded by sync cadence**, same as balances. The columns hold
  the freshest values written on the last successful `/liabilities/get`.
- Any future "what's owed / when" use case should read these `Account` columns
  or call `/liabilities/get` directly — the values are not reconstructable from
  transactions.
