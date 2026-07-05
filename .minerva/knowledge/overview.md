# Knowledge overview

<!-- synthesis-watermark: 008 -->

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

## Recovering a disconnected Item

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
