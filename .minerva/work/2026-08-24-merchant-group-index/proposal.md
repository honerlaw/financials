# Proposal: merchant-group-index

**Date**: 2026-08-24
**Status**: Draft

## Goal

Serve `/subscriptions` and `/bills` from a persisted merchant-group index that is
maintained incrementally at sync time, so neither page performs fuzzy merchant
matching on load.

## Why

`_group_transactions` (`app/subscriptions.py:81`) compares every distinct merchant
key against every group found so far, constructing a fresh `SequenceMatcher` per
pair (`app/subscriptions.py:46`). Profiling the real detector at 1000 distinct
merchants shows exactly C(1000,2) = 499,500 comparisons, with 99.4% of page
compute inside that one loop.

Measured against a synthetic corpus:

| distinct merchants | seconds |
|---|---|
| 500 | 1.3 |
| 1000 | 5.0 |
| 2000 | 20.4 |
| 3000 | 45.3 |

Doubling merchants quadruples the time. The cost is driven by *distinct
merchants*, not row count — holding merchants fixed while growing transactions to
8000 stays flat at 0.55s — so it degrades permanently as one-off purchases
accumulate, and no amount of pruning old transactions helps.

`/bills` calls the same `_group_transactions` (`app/bills.py:73`) and pays the
identical cost on every load. Both pages recompute from scratch per request with
no caching (`app/routes.py:332`, and the `/bills` route).

Production merchant cardinality is unmeasured — DB access from this workstation
is firewalled — so the real-world speedup is projected from the synthetic figures
above, not observed. The quadratic mechanism is confirmed; the seconds-cost on
this user's data is inferred.

## Approach

1. **Schema.** `transactions.merchant_key` (nullable, indexed); `merchant_groups`
   (id, `canonical_key`, `algo_version`); `merchant_group_keys` (`key` unique →
   `group_id`).

   `transactions.merchant_key` stores the *grouping key*, not the normalized name:
   it is `entity:<merchant_entity_id>` when Plaid supplied an entity id, and the
   output of `normalize_merchant(merchant_name or description)` otherwise. The same
   value is what `merchant_group_keys.key` holds, so the read path is a single
   indexed join with no normalization at render time.

   `merchant_groups.canonical_key` is frozen at group creation rather than
   recomputed from the group's name distribution on each load — that freeze is what
   makes incremental matching stable.

2. **Write path.** `_extract_fields` (`app/sync.py:318`) gains one entry so
   `_upsert_transactions` persists `merchant_key` on every insert and update.

3. **Index update.** New `app/merchant_groups.py` holds the DB-backed logic;
   `app/subscriptions.py` stays a pure module. Called at the tail of
   `_sync_institution`, it opens with a `NOT EXISTS` query for transactions whose
   key has no group — zero rows on a quiet sync. Each genuinely new key then
   fuzzy-matches against existing canonical keys and either joins a group or opens
   one: O(new keys x groups).

   The trigger is deliberately *not* gated on `added_count`/`removed_count`.
   `_upsert_transactions` returns a count of newly-inserted rows only
   (`app/sync.py:436`), so a sync carrying only `modified` transactions — a pending
   charge resolving, Plaid correcting a merchant name — returns 0 and would skip
   exactly the case where a key changed. The `NOT EXISTS` query derives the same
   answer from the data and is additionally correct under backfills and manual DB
   edits.

4. **Version stamp.** `GROUPING_ALGO_VERSION`; a mismatch against the stored value
   triggers exactly one full rebuild on the next sync, so changing
   `FUZZY_THRESHOLD` or `normalize_merchant` cannot leave the index silently wrong.

5. **Read path.** Split `detect_subscriptions` / `detect_bills` into `*_from_groups`
   cores plus the existing transaction-taking wrappers, preserving the tested
   pure-function contract. Routes feed pre-grouped input. If the index is missing
   or incomplete, the wrapper computes in memory exactly as today and the result is
   persisted — correct once, slow once. The migration therefore adds nullable
   columns only and runs no data backfill.

6. **Prefilter.** Fold in a length bound plus difflib's `real_quick_ratio` /
   `quick_ratio` upper bounds before the full `ratio()` call, reusing one
   `SequenceMatcher` per key so the b-chain is built once instead of per pair. This
   preserves the `_similar` predicate exactly — verified to produce byte-identical
   groupings at 500/1000/2000/3000 merchants — and measured 5.5-5.8x, which is what
   makes cold start and rebuilds cost ~8s instead of ~45s.

## Success criteria

- `/subscriptions` and `/bills` perform zero fuzzy merchant matching once the index
  is warm.
- A sync that changed nothing performs a small constant number of indexed
  queries (3) and no fuzzy matching, with the constant independent of corpus
  size. (Amended 2026-08-24 — see replan.md; the original said "one indexed
  query", which measurement disproved.)
- The existing `tests/test_subscriptions.py` and `tests/test_bills.py` fixtures pass
  through **both** the in-memory and the indexed grouping paths.
- A test asserts that introducing a new merchant never reassigns an existing
  transaction's group.
- Bumping `GROUPING_ALGO_VERSION` triggers exactly one full rebuild.
- The in-memory fallback path remains reachable and correct when the index is absent.

## Open Questions

- Production merchant cardinality is unmeasured, so the projected speedup is not
  yet confirmed against real data. Worth measuring once shipped.
- Should the in-memory fallback log when it fires? If it fires routinely the index
  is not doing its job, and nothing would currently say so. Knowledge entry 023's
  lesson was that the silence, not the missing row, was the real defect.
- Group assignment becomes first-come-wins rather than today's sorted-order-wins.
  This is accepted (it makes a stream's identity stop reshuffling when an unrelated
  merchant appears) but it is a genuine behavioural change on borderline fuzzy
  matches, and the numeric constants it interacts with are themselves provisional
  per knowledge entry 003.
