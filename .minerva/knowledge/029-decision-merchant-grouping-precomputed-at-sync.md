# Merchant grouping is precomputed at sync time, not on page load

**Date**: 2026-08-24
**Type**: decision
**Summary**: `/subscriptions` and `/bills` grouped merchants with an O(distinct-merchants²) fuzzy match on every request (20s at 2000 merchants); grouping now happens once at sync time into `merchant_groups`/`merchant_group_keys`, while everything date-dependent stays uncached.
**Context**: .minerva/work/2026-08-24-merchant-group-index

## Context

`_group_transactions` in `app/subscriptions.py` compared every distinct merchant
key against every group found so far, constructing a `SequenceMatcher` per pair.
Both `/subscriptions` and `/bills` called it on every request
([[005-decision-bills-inactive-override]] — bills reuses the subscriptions
detector wholesale).

Measured against a synthetic corpus: 1.3s at 500 distinct merchants, 5.0s at
1000, 20.4s at 2000, 45.3s at 3000. Profiling at 1000 merchants showed exactly
C(1000,2) = 499,500 comparisons and 99.4% of page compute inside that one loop.

The cost is driven by **distinct merchants, not transaction count** — holding
merchants fixed while growing transactions to 8000 stayed flat at 0.55s. That
matters: it means the page degrades permanently as one-off purchases accumulate,
and no retention policy on transactions helps.

## Finding

Grouping is now persisted and updated incrementally:

- `transactions.merchant_key` holds the grouping key, written at upsert —
  `entity:<merchant_entity_id>` when Plaid supplied one, else
  `normalize_merchant(merchant_name or description)`.
- `merchant_groups` / `merchant_group_keys` map keys to groups. A key already
  assigned is never rematched; only genuinely new keys are compared, against the
  frozen canonical keys of existing groups.
- The read path is a join plus dict bucketing. Warm page load measured **0.06s**
  against the 20.4s baseline on the same 2000-merchant corpus.

Three things were deliberately *not* done:

1. **Nothing date-dependent is stored.** `active`, `next_date` and bills'
   `payment_status` are recomputed per request from the grouped transactions. A
   stored `active` flag would be wrong the moment a stream lapsed, and the
   trigger for refresh is "transactions changed" — which never fires for a
   subscription that simply stopped being charged.
2. **The trigger is a `NOT EXISTS` query, not the sync's counters.**
   `_upsert_transactions` returns newly-*inserted* rows only, so a sync carrying
   only `modified` transactions reports zero while a merchant key has in fact
   changed. Asking the data costs three indexed queries and is also correct under
   backfills and manual edits.
3. **The in-memory grouper was kept.** It is the fallback when the index is cold
   or unusable, and the reference implementation the indexed path is tested
   against. A slow page is a bad day; an empty one looks like data loss.

`_similar` also gained length and `quick_ratio` bounds that reject only pairs
which provably cannot reach the threshold — the predicate is unchanged (pinned by
a differential test against the pre-optimization implementation) and the cold
build got 5.8x cheaper.

## Implications

- **Group assignment is first-come-wins**, where a full recompute is
  sorted-order-wins. Accepted deliberately: a stream's identity now stops
  reshuffling when an unrelated merchant appears. It does mean the indexed and
  in-memory paths can differ on borderline fuzzy matches.
- Detection semantics are untouched — [[003-decision-subscriptions-cadence-only-detection]]
  still holds in full, and amount similarity still never gates.
- Any future page that needs merchant grouping should read the index rather than
  calling `_group_transactions`.

## Related

- [[003-decision-subscriptions-cadence-only-detection]] — the detection rules this index feeds, unchanged by it
- [[005-decision-bills-inactive-override]] — why /bills shares the same grouping and therefore the same fix
- [[030-bug-derived-index-needs-a-nothing-to-compute-state]] — a failure mode this index shipped with and had to fix
- [[032-constraint-plaid-entity-ids-must-never-fuzzy-merge]] — the rule that keeps the indexed and in-memory paths agreeing
- [[031-pattern-version-stamp-must-invalidate-derived-inputs]] — see also
- [[033-pattern-sqlite-tests-cannot-catch-postgres-transaction-aborts]] — see also
