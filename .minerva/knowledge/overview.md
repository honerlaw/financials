# Knowledge overview

<!-- synthesis-watermark: 006 -->

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

## Testing time-dependent code

[[004-pattern-seed-relative-dates-in-time-sensitive-tests]] is the
cross-cutting testing rule: any test exercising a code path that calls
`date.today()` must seed fixtures relative to today (or freeze the clock) —
fixed calendar dates drift across behavioral boundaries and turn green tests
into delayed-fuse failures. Pure functions sidestep this by taking the
reference date as a parameter.

## Limitations

The `synthesis-watermark` above is a new-scope-only floor: it attests that
entries up to that NNN were considered at synthesis time, not that this
body reflects later in-place edits to those entries. Entries promoted after
this synthesis will show as un-synthesized until the next refresh.
