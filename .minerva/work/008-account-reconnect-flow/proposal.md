# Proposal: account-reconnect-flow

**Date**: 2026-06-30
**Status**: Shipped (2026-06-30)

## Goal

Surface a persistent warning banner on every authenticated page whenever a
connected institution's Plaid item needs re-authentication
(`status == 'login_required'`), and fix the currently-broken reconnect action so
it re-authenticates the **existing** item via Plaid **update mode** instead of
erroring out as a duplicate new connection.

## Why

When Plaid returns `ITEM_LOGIN_REQUIRED`, `app/sync.py` silently flips the
institution to `status='login_required'` and stops pulling its transactions.
Today that state surfaces only as a small badge buried in `/settings`, so the
user went days without noticing and lost ~$2.5k of transactions.

Worse, the existing "Re-connect" button is broken: it reuses the
new-connection flow (`connectInstitution()` → `create_link_token` →
`exchange_token`), which mints a products link token, exchanges it for an item,
then trips the slug-uniqueness guard in `exchange_token` and returns
"`<name> is already connected`". Reconnect is therefore impossible. Both halves
of the loop — *notice it* and *fix it* — are currently broken, which is why
this is one cohesive work unit.

## Approach

1. **Expose state (context processor).** `app/routes.py`: add
   `@bp.app_context_processor` that, **only** for authenticated sessions
   (`session.get('authenticated')`), queries
   `Institution.query.filter_by(status='login_required').order_by(Institution.name).all()`
   and injects `login_required_institutions` into every template; returns an
   empty list (no DB query) when unauthenticated, so the login page and any
   future error pages stay cheap.

2. **Banner + shared JS.** `app/templates/base.html`: when
   `login_required_institutions` is non-empty (and authenticated), render a
   Bootstrap `alert-warning` banner naming **each** affected institution, each
   with its own "Reconnect" button calling `reconnectInstitution(id)`. Load the
   Plaid Link SDK and a shared `reconnectInstitution(id)` helper in `base.html`
   (gated on authenticated) so the action works from any page. The helper:
   `fetch` the update-mode link token, `Plaid.create({token, onSuccess: (_pt, _meta) => fetch reconnect/<id> then reload})`
   — it deliberately ignores the `onSuccess` public_token (update mode performs
   no token exchange).

3. **Update-mode link token.** `app/plaid_client.py`: add
   `create_update_link_token(access_token)` that calls `link_token_create`
   **with** `access_token` and **without** `products` **and without**
   `transactions` (both are link-time-only parameters that Plaid may reject in
   update mode) — passing only `client_name`, `country_codes`, `language`,
   `user`, `access_token`.

4. **Endpoints.** `app/routes.py`, both decorated `@login_required`:
   - `POST /api/plaid/update_link_token/<int:institution_id>` → returns
     `{link_token}` from the update-mode call; 404 if the institution is missing.
   - `POST /api/plaid/reconnect/<int:institution_id>` → set `status='active'`,
     commit, kick a background sync thread (same pattern as `/api/sync`), return
     `{status:'ok'}`; 404 if missing. (The background sync sweeps all active
     institutions, identical to `/api/sync` — accepted as consistent behavior.)

5. **Fix settings.** `app/templates/settings.html`: point the per-row
   "Re-connect" button at the shared `reconnectInstitution({{ inst.id }})`;
   remove its now-duplicate Plaid SDK `<script>` tag (moved to `base.html`).
   Keep `connectInstitution` (new), `removeInstitution`, `forceFullResync`.

6. **Tests.** `tests/test_routes.py`: banner present when an institution is
   `login_required` / absent when all active; `update_link_token` returns a
   token and 404s on unknown id; `reconnect` flips status to `active` and 404s
   on unknown id. `tests/test_plaid_client.py`: `create_update_link_token`
   passes `access_token` and omits both `products` and `transactions`.

## Success criteria

- With an institution at `status='login_required'`, `GET /` renders a warning
  banner naming it and exposing a Reconnect button.
- With all institutions `active`, `GET /` renders no banner.
- `POST /api/plaid/update_link_token/<id>` returns a link token built in update
  mode (access_token passed; `products` and `transactions` omitted); returns
  404 for an unknown id.
- `POST /api/plaid/reconnect/<id>` sets the institution back to `active` and
  returns ok; returns 404 for an unknown id.
- Both new endpoints require authentication (`@login_required`).
- The settings "Re-connect" button and the banner both invoke the same
  update-mode `reconnectInstitution(id)` path — neither uses the
  new-connection flow.
- No new test failures versus baseline (`pytest`). (Pre-existing, out-of-scope:
  `tests/test_bills.py::test_inactive_sorts_last` fails on 2026-06-30 due to
  documented date-relative test fragility, knowledge `004`.)

## Open Questions

- None. (Resolved during proposal: reconnect auto-kicks a background sync to
  close the missing-transactions gap; the banner shows one Reconnect button per
  affected institution.)
