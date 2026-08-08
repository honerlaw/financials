# Knowledge index
<!-- index-watermark: 015 -->

## Decisions

- [[001-decision-plaid-accounts-piggyback-on-sync]] — Account metadata is upserted from the accounts array `transactions/sync` already returns, instead of a separate `accounts/get` round-trip — so metadata freshness is bounded by the sync schedule.
- [[002-decision-plaid-balance-refresh-via-dedicated-endpoint]] — Balances carried by `transactions/sync` are cached snapshots; a dedicated `/accounts/balance/get` call after each sync overwrites them with authoritative real-time values.
- [[003-decision-subscriptions-cadence-only-detection]] — Recurring-stream detection gates on cadence regularity alone — amount similarity must never gate, or card payments and utilities disappear from `/subscriptions`.
- [[005-decision-bills-inactive-override]] — Inactive recurring outflows get payment_status='inactive' in detect_bills(), not 'unpaid' — prevents false alarms for cancelled/lapsed streams
- [[006-decision-bills-payment-status-algorithm]] — Monthly payment status for bills uses median day-of-month from history + ±PAYMENT_WINDOW (6 days) window check against current-month transactions
- [[007-decision-plaid-reconnect-update-mode]] — Reconnecting an existing Plaid Item requires update mode (`create_update_link_token` with `access_token`, without `products`/`transactions`); the new-connection flow mints a new Item and always trips the slug guard.
- [[008-decision-dashboard-spend-and-weekly-budget]] — Dashboard spend chart + weekly $1000 budget tracker — spend = positive amount excluding transfer/loan-payment categories, weeks summed over full Sun–Sat boundaries, current-month default on a self-labeled section
- [[009-decision-chart-click-window-filter]] — Clicking a dashboard chart week/day filters the transactions table via ?start/?end date-window params, which take precedence over ?month; the spending chart stays month-scoped
- [[010-decision-budget-alert-notifier]] — Weekly-budget SMS alerts fire from the sync path — per-recipient dedup via BudgetAlert, in-process lock + unique constraint for no-double-send (relies on --workers 1), record-after-send retry, soft-disabled unless all Twilio config is set
- [[011-decision-doppler-hybrid-config]] — Config/secrets managed via Doppler with a backward-compatible entrypoint — doppler run only when DOPPLER_TOKEN is set (else plain env); DB URLs stay from DO's managed binding, protected by --preserve-env; CLI pinned; fail-closed
- [[014-decision-plaid-liabilities-piggyback-on-sync]] — Liability due dates and statement balances come from a dedicated `/liabilities/get` call after the balance refresh, written to three nullable `Account` columns, non-fatally.
- [[015-decision-liability-consent-requires-update-mode]] — Plaid consent is fixed at link time: Items linked before a product was consented return `ADDITIONAL_CONSENT_REQUIRED` and can only be re-consented through update mode.

## Bugs

## Patterns

- [[004-pattern-seed-relative-dates-in-time-sensitive-tests]] — Any test exercising code that calls `date.today()` must seed fixtures relative to today (or freeze the clock) — fixed calendar dates drift across behavioral boundaries into delayed-fuse failures.
- [[012-pattern-fetch-content-type-session-detection]] — A `fetch()` against a Flask `@login_required` route cannot detect session expiry with `!r.ok` — the browser follows the 302 to `/login` transparently, so check the response Content-Type before parsing.

## Constraints
