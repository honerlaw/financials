# Proposal: on-demand-relink

**Date**: 2026-07-12
**Status**: Shipped (2026-07-12)

## Goal

Let the user relink any connected institution **on demand** — not only when it
hits `ITEM_LOGIN_REQUIRED` — so an existing Item can re-consent to newer Plaid
products and refresh its permissions. The immediate driver: Items linked before
unit 014 were never consented to the `liabilities` product, so their due-date /
balance fields stay empty until they re-consent.

## Why

Unit 008 built an update-mode reconnect flow, but it is only surfaced when an
institution is `login_required` (the reconnect banner + the settings
"Re-connect" button). There was no way to *proactively* relink a healthy,
active Item. And even if there were, the update-mode link token
(`create_update_link_token`) omitted all product parameters, so going through
it would re-authenticate but **not** expand consent — an old Item would still
lack `liabilities`.

Unit 014 added `liabilities` as an `additional_consented_products` entry on
`create_link_token`, but that only affects *new* links. Existing Items need a
consent-expansion path, which Plaid provides through update mode.

## Approach (as shipped)

### 1. Update-mode token re-consents to the current product set — `app/plaid_client.py`

`create_update_link_token` now passes
`additional_consented_products=[Products('liabilities')]` alongside
`access_token` (mirroring `create_link_token`). Plaid accepts
`additional_consented_products` in update mode — it is the documented mechanism
for adding consent for a new product to an existing Item. `products` /
`transactions` are still omitted (Plaid rejects those when `access_token` is
present). So every relink now re-presents `liabilities` consent, and an older
Item catches up to the current product set.

### 2. Relink button for every institution — `app/templates/settings.html`

Active institutions now render a **Relink** button next to their "Active"
badge, wired to the existing shared `reconnectInstitution(id, this)` helper
(the same update-mode path the banner and the `login_required` "Re-connect"
button already use). `login_required` institutions are unchanged (still show
the warning badge + "Re-connect"). A tooltip explains that relinking refreshes
permissions to grant newly-added data like due dates & balances.

### 3. Reconnect endpoint generalized — `app/routes.py`

No behavior change: `POST /api/plaid/reconnect/<id>` already (re)asserts
`active` and kicks a background `sync_all_institutions()`. Its docstring now
documents the proactive-relink case — on the first relink that adds
`liabilities` consent, the kicked sync's `_refresh_liabilities` populates the
new fields. Re-asserting `active` on an already-active Item is a harmless no-op.

### 4. Tests

- `tests/test_plaid_client.py::test_create_update_link_token` — asserts the
  update-mode token still omits `products`/`transactions` **and** now includes
  `liabilities` in `additional_consented_products`.
- `tests/test_routes.py::test_settings_shows_relink_for_active_institution` —
  the settings page renders a Relink button for an active institution.
- `tests/test_routes.py::test_reconnect_keeps_active_institution_active` — a
  proactive relink of an active Item returns ok and leaves it active.

## Success criteria

- Update-mode link tokens re-consent to `liabilities` so relinking an old Item
  grants it. ✅
- Every active institution exposes a Relink action in settings; the flow reuses
  the update-mode reconnect path (no new-connection / token-exchange path). ✅
- `login_required` institutions keep their existing Re-connect affordance. ✅
- Relinking kicks a sync that backfills transactions and populates liability
  fields once consent is granted. ✅
- `pytest` passes with no `--deselect`. ✅ (193/193)

## Open Questions

- Depository-only Items granted `liabilities` consent still return
  `NO_LIABILITY_ACCOUNTS`, which `_refresh_liabilities` already treats as a
  benign no-op — relinking them is harmless but simply has nothing to populate.
