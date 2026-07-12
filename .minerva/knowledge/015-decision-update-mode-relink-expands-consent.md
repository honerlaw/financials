# On-demand relink uses Plaid update mode + `additional_consented_products` to expand consent on existing Items

**Date**: 2026-07-12
**Type**: decision
**Context**: .minerva/work/015-on-demand-relink (see git history if the worktree has been cleaned up)

## Context

Adding a new Plaid product to the app (`liabilities`, unit 014) only affects
*new* links — `create_link_token` sets `additional_consented_products`, but
Items already linked never see that consent screen and so can't return the new
data. We needed a way to bring existing Items up to the current product set, and
a UI to trigger it whenever the user wants (not just on `ITEM_LOGIN_REQUIRED`).

## Finding

- **Update mode is the consent-expansion path.** `create_update_link_token`
  passes `access_token` (which puts Link in update mode for that Item) **plus**
  `additional_consented_products=[Products('liabilities')]`. Plaid accepts
  `additional_consented_products` in update mode and re-presents the consent
  screen; `products` and `transactions` must still be omitted (Plaid rejects
  those link-time-only params when `access_token` is present).
- **Relink reuses the unit-008 reconnect plumbing end to end.** The settings
  "Relink" button (now shown for *active* institutions, not just
  `login_required` ones) calls the same `reconnectInstitution(id)` JS helper →
  `POST /api/plaid/update_link_token/<id>` → Plaid Link update mode →
  `POST /api/plaid/reconnect/<id>`, which re-asserts `active` and kicks
  `sync_all_institutions()`. No new-connection / token-exchange path is
  involved (that path would trip the slug-uniqueness guard — see unit 008).
- The kicked sync's `_refresh_liabilities` (unit 014) populates the new fields
  on the first relink that adds consent.

## Implications

- **This is the general recipe for any future product added after initial
  link.** Add it to `additional_consented_products` in *both*
  `create_link_token` and `create_update_link_token`, keep the two lists in
  sync, and existing Items pick it up on their next relink. Keep `products` out
  of the update-mode request.
- **Re-asserting `active` on an already-active Item is a deliberate no-op.** The
  reconnect endpoint is shared between recovery (`login_required` → `active`)
  and proactive relink (`active` → `active`); the value is the kicked sync, not
  the status write.
- **Relinking a depository-only Item is harmless but empty.** It gains
  `liabilities` consent but `/liabilities/get` returns `NO_LIABILITY_ACCOUNTS`,
  which `_refresh_liabilities` treats as benign (see unit 014 knowledge).
