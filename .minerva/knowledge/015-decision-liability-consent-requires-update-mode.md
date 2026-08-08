# Pre-consent Items return `ADDITIONAL_CONSENT_REQUIRED`; only update mode can grant the consent

**Date**: 2026-08-08
**Type**: decision
**Summary**: Plaid consent is fixed at link time: Items linked before a product was consented return `ADDITIONAL_CONSENT_REQUIRED` and can only be re-consented through update mode.
**Context**: .minerva/work/015-fix-liability-additional-consent (see git history if the worktree has been cleaned up)

## Context

[[014-decision-plaid-liabilities-piggyback-on-sync]] added `/liabilities/get`
to the sync and correctly predicted that every Item linked *before* that
change was never consented to the `liabilities` product, so those calls would
fail on every sync and had to be treated as benign. It named the wrong Plaid
error code, though. In production the sync log filled with:

```
✗ liability refresh failed: ADDITIONAL_CONSENT_REQUIRED: Status Code: 400
```

`ADDITIONAL_CONSENT_REQUIRED` — not `PRODUCTS_NOT_SUPPORTED` — is what Plaid
returns when the Item exists and the institution supports the product, but the
Item was never consented to it. It was absent from
`_BENIGN_LIABILITY_ERROR_CODES`, so `_refresh_liabilities` annotated every
`SyncLog` for every institution.

## Finding

- **`ADDITIONAL_CONSENT_REQUIRED` is the never-consented code.**
  `PRODUCTS_NOT_SUPPORTED` means the *institution* cannot serve the product;
  `NO_LIABILITY_ACCOUNTS` / `NO_ACCOUNTS` mean the Item has no such accounts.
  All four are now in `_BENIGN_LIABILITY_ERROR_CODES` in `app/sync.py`.
- **Consent is granted through Plaid update mode, not by re-linking.**
  `create_update_link_token` now passes
  `additional_consented_products=[Products('liabilities')]` alongside
  `access_token`. Verified against plaid-python 39.2.0 that
  `LinkTokenCreateRequest` accepts both together — and the constraint from
  [[007-decision-plaid-reconnect-update-mode]] still holds: `products` and
  `transactions` stay omitted, and `onSuccess` still performs no token
  exchange.
- **The "Re-connect" button in `/settings` is no longer gated on
  `status == 'login_required'`.** It renders for every institution; only the
  "Login required" badge stays gated. Without this, a healthy Item that merely
  needs extra consent had no way to trigger update mode, so the fix would have
  been unreachable.

## Implications

- **Adding any future Plaid product to `additional_consented_products` only
  affects Items linked afterwards.** Existing Items keep returning
  `ADDITIONAL_CONSENT_REQUIRED` until the user re-connects each one. Budget for
  that migration step whenever a new product is consented — it is not automatic
  and there is no server-side way to grant it.
- **Re-connecting is a routine, safe action, not a failure recovery.** Update
  mode preserves the Item, the access token, and the cursor;
  `/api/plaid/reconnect/<id>` writes `status='active'` (a no-op for a healthy
  Item) and kicks the sync that pulls the newly-consented data.
- **Suppressing the code costs feedback.** Because the error is now benign,
  nothing tells the user whether a given institution still lacks the consent —
  the only signal is that its liability columns stay null. A persisted
  `needs_liability_consent` flag driving a targeted banner (mirroring the
  `login_required` context processor) is the recorded follow-up if that becomes
  annoying.

## Related

- [[014-decision-plaid-liabilities-piggyback-on-sync]] — builds on
  the liabilities feature whose error-code assumption this corrects.
- [[007-decision-plaid-reconnect-update-mode]] — builds on
  update mode itself — the same mechanism, used here to grant consent rather than re-authenticate.
