# Knowledge overview

<!-- synthesis-watermark: 015 -->

## Plaid data flow: piggyback, then refresh

Account metadata is never fetched on its own round-trip:
[[001-decision-plaid-accounts-piggyback-on-sync]] established that
`transactions/sync` already carries the accounts array, so the sync path
upserts accounts from its last non-empty page instead of calling
`accounts/get`. The piggybacked balances are treated as cached snapshots —
[[002-decision-plaid-balance-refresh-via-dedicated-endpoint]] layers a
dedicated `/accounts/balance/get` call after sync to overwrite balance
fields with authoritative values. Together: metadata freshness is bounded by
the sync schedule; balance freshness is not.

[[014-decision-plaid-liabilities-piggyback-on-sync]] extends the same shape a
third time: due dates and statement balances are liability attributes that
exist on no other payload, so a `/liabilities/get` call follows the balance
refresh and writes three nullable `Account` columns. The recurring contract
across all three layers is that **a post-sync refresh is never fatal** — a
Plaid `ApiException` annotates `SyncLog.error` and the transactions still
land. The corollary is a noise problem: an error that recurs on every sync for
a structural reason buries the real ones, so "this Item has no liabilities"
responses are classified benign and dropped.

## Plaid product consent, and update mode as the tool for both

When Plaid returns `ITEM_LOGIN_REQUIRED`, sync flips the institution to
`status='login_required'` and stops importing. [[007-decision-plaid-reconnect-update-mode]]
records the hard-won rule for getting it back: reconnect must use Plaid
**update mode** (`create_update_link_token`, built with `access_token` and
without `products`/`transactions`), *never* the new-connection flow — the
latter mints a new Item and always trips the slug-uniqueness guard, so it is
structurally incapable of reconnecting. Update mode keeps the access token, so
`onSuccess` performs no token exchange; the reconnect endpoint sets
`status='active'` **before** kicking a sync (sync filters on `active`), and a
still-invalid Item simply re-trips `ITEM_LOGIN_REQUIRED` and flips back —
self-healing. Visibility is a context processor injecting a warning banner on
every authenticated page.

[[015-decision-liability-consent-requires-update-mode]] found update mode's
second job, and with it the general rule for adding a Plaid product to a live
integration. Consent is fixed at link time, so making `liabilities` an
additional consented product only helped Items linked *afterwards*; every
older Item returned `ADDITIONAL_CONSENT_REQUIRED` on every sync. There is no
server-side way to grant it — the user must re-consent through update mode,
which is why `create_update_link_token` now carries
`additional_consented_products` and why "Re-connect" is offered for healthy
institutions rather than only failed ones. Budget for that per-Item migration
whenever a new product is consented. The entry also corrects 014's guess at
which error code the never-consented case returns, and notes the cost of
suppressing it: nothing now signals *which* institutions still lack consent,
only that their liability columns stay null.

## Deriving views from stored transactions

Higher-level views are computed from the transactions table rather than new
Plaid products. [[003-decision-subscriptions-cadence-only-detection]] records
the design stance of the `/subscriptions` recurring-stream detector: cadence
regularity is the only detection gate (amount similarity must never gate, or
card payments and utilities vanish), median-bucket fit alone is insufficient
without a per-gap regularity requirement, and the "varies" badge uses MAD so
single price hikes don't false-flag. Its numeric thresholds are provisional
pending real synced data.

The `/bills` page extends this pattern with a monthly payment-status layer.
[[006-decision-bills-payment-status-algorithm]] records the algorithm: expected
day-of-month is the median of historical transaction `.day` values; a bill is
`paid` if any current-month transaction falls within ±6 days of that expected
date, `upcoming` if the window hasn't opened yet, and `unpaid` otherwise. The
±6-day window matches the monthly cadence tolerance already in `CADENCES`.
[[005-decision-bills-inactive-override]] records the safety rule that prevents
false alarms: a stream past 1.5× its cadence age-out boundary gets
`payment_status='inactive'` (with dimmed rendering) instead of `'unpaid'` — a
lapsed cancelled bill must never surface as an overdue obligation.

The dashboard spend chart and weekly budget tracker are the third derived view.
[[008-decision-dashboard-spend-and-weekly-budget]] records its load-bearing
rules: "spend" is a positive `amount` **excluding** Plaid `TRANSFER*` /
`LOAN_PAYMENTS` categories (so credit-card payments and transfers don't
double-count against the budget), with null-category outflows counted as spend
(and therefore potentially over-counting older, uncategorized data). The
weekly $1000 tracker sums each Sun–Sat week in **full** — padding the query to
whole week boundaries so edge weeks straddling the month aren't undercounted —
and flags the current week only when it overlaps the displayed month. The
spending section defaults to the current month on a self-labeled header rather
than changing the transactions table's all-time default.

Those charts are also interactive. [[009-decision-chart-click-window-filter]]
records that clicking a week card or day bar filters the transactions table to a
`?start`/`?end` date window (a day click = 1 day, a week click = the 7-day
Sun–Sat window), computed with **local** date math so negative-UTC zones don't
roll back a day. The window takes precedence over `?month=` for the table, its
infinite-scroll pages, and the account-totals strip (via
`_table_date_bounds`), while the spending chart itself deliberately stays
month-scoped so it remains a stable picker. A day-bar click filters to *all*
transactions that day, not only spend-classified ones.

## Acting on synced data: proactive alerts

Beyond deriving views, the sync path now fires an outbound side-effect.
[[010-decision-budget-alert-notifier]] records the design of the weekly-budget
SMS alerts: after every sync, each configured recipient is texted once per
Sun–Sat week for each newly-crossed 50/75/100% threshold of the current week's
household spend (reusing `week_spend` over the same `is_spend` definition as the
dashboard). Load-bearing decisions: dedup is **per-recipient**
(`BudgetAlert` unique on week+threshold+recipient); no-double-send comes from a
module-level lock **plus** that unique constraint, correct only under the
`--workers 1` invariant the APScheduler already assumes (a gap that is *not*
runtime-enforced — see the unit's followups); the row is written **after** a
successful send so a failure retries rather than silently dropping a milestone
(duplicate > miss, for a budget alert); and the whole feature is **soft-disabled**
(a clean no-op, `twilio` never imported) unless all four Twilio/recipient env
vars are set, so it ships inert. The hook is non-fatal, mirroring
`_refresh_balances` — a notifier failure never aborts a sync.

## Configuration and secrets

All config is read through `os.getenv` in `app/__init__.py`, which made moving to
a secrets manager a pure deployment change. [[011-decision-doppler-hybrid-config]]
records the Doppler migration: the CLI is baked into the image (pinned, signed apt
repo) and the app runs via `doppler run` **only when `DOPPLER_TOKEN` is set** —
otherwise it falls back to plain environment variables, so the same image boots
either way and the production cutover is staged and reversible (and fail-closed:
a bad token aborts boot). It is a **hybrid**: `DATABASE_URL`/`DATABASE_ADMIN_URL`
stay injected by DigitalOcean's managed-database binding rather than Doppler, and
the entrypoint passes `--preserve-env` for exactly those so the DO values always
win. Application code did not change — Doppler only populates the environment.

## Client-side gotchas

[[005-pattern-fetch-content-type-session-detection]] records why `fetch()`
against a `@login_required` route cannot detect session expiry with `!r.ok`:
the browser follows the 302 to `/login` transparently, so the JS sees a 200
with an HTML body, `r.json()` throws, and an infinite-scroll observer retries
the same broken request forever. Check the response `Content-Type` for
`application/json` *before* parsing, and redirect to `/login` when it isn't.

## Testing time-dependent code

[[004-pattern-seed-relative-dates-in-time-sensitive-tests]] is the
cross-cutting testing rule: any test exercising a code path that calls
`date.today()` must seed fixtures relative to today (or freeze the clock) —
fixed calendar dates drift across behavioral boundaries and turn green tests
into delayed-fuse failures. Pure functions sidestep this by taking the
reference date as a parameter — the stance `spending.py`, `bills.py`, and
`subscriptions.py` all follow.

## Limitations

The `synthesis-watermark` above is a new-scope-only floor: it attests that
entries up to that NNN were considered at synthesis time, not that this
body reflects later in-place edits to those entries. Entries promoted after
this synthesis will show as un-synthesized until the next refresh.
