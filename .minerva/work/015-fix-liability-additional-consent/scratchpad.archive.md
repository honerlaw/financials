# Scratchpad: fix-liability-additional-consent

> **Ephemeral working memory.** Most of what lands here is noise — small
> observations, dead ends, running notes. `minerva:promote` decides at the end
> which few entries are durable enough for `.minerva/knowledge/`.

## Quick decisions 2026-08-08

- [decided] root cause: Plaid returns `ADDITIONAL_CONSENT_REQUIRED` (not
  `PRODUCTS_NOT_SUPPORTED`) for Items linked before unit 014 added the
  `liabilities` consent; the code is absent from `_BENIGN_LIABILITY_ERROR_CODES`,
  so `_refresh_liabilities` annotates every SyncLog. Grounded in
  `app/sync.py:122-146` and knowledge entry 014.
- [decided] scope check: single work unit — three small coordinated edits
  (sync constant, link-token param, template), no schema change, no new route.
- [decided] approach: suppress the code *and* make re-consent reachable
  (update-mode consent + always-available Re-connect button). Dominant over
  suppress-only, which would leave unit 014's feature permanently dead for
  every pre-existing Item; dominant over a persisted `needs_consent` flag +
  banner, which costs a migration and a context processor for a one-time
  three-institution chore.
- [decided] soundness: the only third-party contract in play is update-mode
  consent. Verified plaid-python 39.2.0 accepts `access_token` +
  `additional_consented_products` on the same `LinkTokenCreateRequest`;
  `products`/`transactions` stay omitted per knowledge entry 007. Residual
  runtime uncertainty recorded as an Open Question, failure mode contained.
