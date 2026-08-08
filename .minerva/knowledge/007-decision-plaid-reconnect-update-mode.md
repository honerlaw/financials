# Plaid reconnect must use *update mode* — the new-connection flow can never reconnect an existing Item

**Date**: 2026-06-30
**Type**: decision
**Summary**: Reconnecting an existing Plaid Item requires update mode (`create_update_link_token` with `access_token`, without `products`/`transactions`); the new-connection flow mints a new Item and always trips the slug guard.
**Context**: .minerva/work/008-account-reconnect-flow (see git history if the worktree has been cleaned up)

## Context

When Plaid returns `ITEM_LOGIN_REQUIRED`, `app/sync.py` flips the institution
to `status='login_required'` and stops importing its transactions. The user
went several days without noticing (~$2.5k of missing transactions), because
the only surfacing was a badge in `/settings`.

Worse, the existing "Re-connect" button was broken. It called
`connectInstitution()` — the **new-connection** flow — which mints a *new*
link token via `create_link_token` (with `products=[transactions]`), runs
Plaid Link in new-Item mode, and then calls `/api/plaid/exchange_token`. That
route derives the institution slug and rejects it with
"`<name> is already connected`" via the slug-uniqueness guard. So reconnect
was structurally impossible — it always tripped the duplicate guard.

## Finding

Reconnecting an existing Item requires Plaid **update mode**, which is a
*different* `link_token_create` call and a *different* success path:

- `PlaidClient.create_update_link_token(access_token)` builds
  `LinkTokenCreateRequest` **with** `access_token` and **without** `products`
  **and without** `transactions`. Both are link-time-only parameters; Plaid
  may reject them when `access_token` is present (verified against
  plaid-python 39.2.0: the request builds fine with `access_token` and no
  `products`/`transactions`).
- In update mode the **access token is unchanged**, so `onSuccess` must **not**
  exchange the returned public_token. The JS helper `reconnectInstitution(id)`
  in `base.html` ignores the `onSuccess(public_token, metadata)` args and
  instead POSTs `/api/plaid/reconnect/<id>`, which just sets `status='active'`
  and kicks a background `sync_all_institutions()` to backfill the gap.
- Both new endpoints (`/api/plaid/update_link_token/<id>`,
  `/api/plaid/reconnect/<id>`) are `@login_required` — without it,
  `reconnect/<id>` would be an open status-manipulation + sync trigger.

Visibility is driven by a context processor
(`inject_login_required_institutions`) that injects
`login_required_institutions` into every template (empty, no DB query, when
unauthenticated), rendering a warning banner in `base.html` on every
authenticated page.

## Implications

- **Never reuse the new-connection flow for reconnect.** `create_link_token` +
  `exchange_token` always creates/expects a new Item and trips the slug guard.
  Any future reconnect/re-auth work must go through update mode.
- **Update mode preserves the Item**, so the `plaid_cursor` and existing
  transaction history are intact — the kicked sync resumes from the stored
  cursor and pulls the transactions missed while disconnected.
- **The reconnect endpoint resets `status='active'` *before* syncing.** This is
  required because `sync_all_institutions()` filters on `status='active'`
  (a `login_required` institution is skipped). If a still-invalid Item is
  reconnected prematurely, the very next sync catches `ITEM_LOGIN_REQUIRED`
  again and flips it back — self-healing, not a bug.
- **Plaid SDK + the `reconnectInstitution` helper now load on every
  authenticated page** (moved to `base.html`); `settings.html` dropped its
  duplicate `<script src>`. This is the accepted tradeoff for a shared helper
  used by both the banner and the settings button.

## Related
- [[015-decision-liability-consent-requires-update-mode]] — see also
