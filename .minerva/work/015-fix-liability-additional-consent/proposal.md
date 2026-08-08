# Proposal: fix-liability-additional-consent

**Date**: 2026-08-08
**Status**: Draft

## Goal

Stop `✗ liability refresh failed: ADDITIONAL_CONSENT_REQUIRED` from annotating
every `SyncLog`, and give the user a working path to actually grant the
`liabilities` consent so the due-date / balance-due fields shipped in unit 014
populate for Items that were linked before that feature existed.

## Why

Unit 014 added `additional_consented_products=[Products('liabilities')]` to
`create_link_token` and a `_refresh_liabilities` step in the sync. Its
knowledge entry
(`.minerva/knowledge/014-decision-plaid-liabilities-piggyback-on-sync.md`)
anticipated that **every Item linked before that change was never consented to
`liabilities`**, and declared those responses benign so they would not bury
real errors in the sync log. It guessed the wrong Plaid error code, though:
`_BENIGN_LIABILITY_ERROR_CODES` covers `PRODUCTS_NOT_SUPPORTED`,
`NO_LIABILITY_ACCOUNTS`, and `NO_ACCOUNTS`, but Plaid returns
**`ADDITIONAL_CONSENT_REQUIRED` (400)** for the "Item exists, but was not
consented to this product" case. So `_refresh_liabilities` falls through to
`return f'liability refresh failed: {code}: {e}'` and every institution
annotates every sync.

Suppressing the message alone would only hide the symptom: all three of the
user's institutions predate unit 014, so their liability columns would stay
null forever and the shipped feature would silently do nothing. The remedy
knowledge entry 014 already names — "their liability fields stay null until the
user re-consents via update mode" — is not actually reachable today:

- `create_update_link_token` omits `additional_consented_products`, so running
  Plaid Link in update mode re-authenticates the Item **without** adding the
  `liabilities` consent; and
- the "Re-connect" button in `/settings` renders only when
  `inst.status == 'login_required'`, so a healthy Item that merely needs extra
  consent has no button to press.

## Approach

Three coordinated edits; no schema change, no new endpoint.

### 1. Treat `ADDITIONAL_CONSENT_REQUIRED` as benign — `app/sync.py`

Add `'ADDITIONAL_CONSENT_REQUIRED'` to `_BENIGN_LIABILITY_ERROR_CODES` and
update the comment above it to name the code that actually arrives for the
never-consented case. This is the code path entry 014 already intended to
cover; the set was simply missing the real code. Unexpected liability failures
keep annotating the log exactly as before.

### 2. Grant `liabilities` consent in update mode — `app/plaid_client.py`

`create_update_link_token` gains
`additional_consented_products=[Products('liabilities')]`. Update mode with an
added consented product is Plaid's documented remedy for
`ADDITIONAL_CONSENT_REQUIRED`, and it composes with the constraint recorded in
`.minerva/knowledge/007-decision-plaid-reconnect-update-mode.md`: `products`
and `transactions` stay omitted (Plaid rejects those link-time-only parameters
alongside `access_token`), and the access token is still unchanged, so the
`onSuccess` no-exchange contract is untouched. Verified against the installed
plaid-python 39.2.0 that `LinkTokenCreateRequest` accepts `access_token` and
`additional_consented_products` together.

### 3. Offer Re-connect for healthy institutions too — `app/templates/settings.html`

Move the "Re-connect" button out of the `login_required` branch so it renders
for every institution, with the existing warning badge/styling still gated on
`login_required`. The button already calls `reconnectInstitution(id)`, which
runs update mode and then POSTs `/api/plaid/reconnect/<id>` — for an
already-active Item that endpoint is a no-op status write plus a background
sync, so reusing it is safe. This is what makes edits 1 and 2 actionable: the
user re-connects each institution once, Link shows the added-consent screen,
and the next sync populates the liability columns.

### Rejected alternatives

- **Suppress the error code only.** Smallest possible diff, but it hides the
  problem rather than fixing it — unit 014's feature would remain permanently
  dead for every existing Item with no signal and no remedy.
- **Persist a `needs_liability_consent` flag on `Institution`** and drive a
  targeted banner from it (mirroring the `login_required` context processor).
  Strictly better UX, but it needs a column, a migration, a context processor,
  and banner markup for what is a one-time, three-institution chore in a
  single-user app. Recorded as a follow-up instead.

## Success criteria

- [ ] `ADDITIONAL_CONSENT_REQUIRED` from `/liabilities/get` no longer writes to
      `SyncLog.error`; a covering test asserts the log records success.
- [ ] Genuinely unexpected liability errors still annotate the log (existing
      test continues to pass).
- [ ] `create_update_link_token` requests `liabilities` as an additional
      consented product, still without `products` / `transactions`; a test
      asserts both halves.
- [ ] `/settings` renders a "Re-connect" button for an `active` institution as
      well as a `login_required` one; the "Login required" badge stays gated on
      `login_required`.
- [ ] Full test suite passes.

## Open Questions

- Whether Plaid honors `additional_consented_products` in update mode for
  these specific institutions cannot be verified locally — it depends on the
  institution and on the Item predating Data Transparency Messaging. The
  failure mode is contained: reconnect surfaces a Link error and nothing else
  changes. If it does not work for an institution, the fallback is to
  disconnect and re-link it, which uses `create_link_token` and already
  consents to `liabilities`.
