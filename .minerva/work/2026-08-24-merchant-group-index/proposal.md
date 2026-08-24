# Proposal: merchant-group-index

**Date**: 2026-08-24
**Status**: Shipped (2026-08-24)

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

*(Rewritten at promote to describe what shipped.)*

1. **Schema.** `transactions.merchant_key` (nullable, indexed) holds the grouping
   key: `entity:<merchant_entity_id>` when Plaid supplied one, else
   `normalize_merchant(merchant_name or description)`, and `''` when the row has
   no groupable merchant at all. `merchant_groups` carries `canonical_key`,
   `algo_version` and `from_entity`; `merchant_group_keys` maps each key to its
   group.

   `canonical_key` is a normalized **name**, frozen at creation — including for
   entity-derived groups, whose representative name is the most common normalized
   name across their live transactions. Storing the raw entity id there would stop
   a bare-name charge ever joining the entity group for the same merchant, splitting
   the stream. `from_entity` then prevents the converse error: two distinct entity
   ids merging because their names look alike.

2. **Write path.** `_extract_fields` persists `merchant_key` on every insert and
   update, via `_grouping_key_for` (the Plaid-object counterpart of
   `grouping_key`).

3. **Index update.** `app/merchant_groups.py` owns the DB-backed logic;
   `app/subscriptions.py` stays pure. `update_index()` runs at the tail of
   `_sync_institution` inside a `db.session.begin_nested()` savepoint, and opens
   with a `NOT EXISTS` query for keys with no group — three indexed queries and
   no matching work on a quiet sync. Entity keys are processed before name keys,
   mirroring how the in-memory grouper seeds from `merchant_entity_id` first.

4. **Version stamp.** A `GROUPING_ALGO_VERSION` mismatch deletes the groups **and
   nulls every `transactions.merchant_key`**, so the backfill re-derives the keys
   with the new normalizer. Deleting only the groups would regroup stale keys and
   report a successful rebuild that changed nothing.

5. **Read path.** `detect_subscriptions_from_groups` / `detect_bills_from_groups`
   take pre-grouped transactions; the original transaction-taking functions remain
   as the pure contract and the fallback. `groups_for_detection()` uses the index
   when usable, builds it on demand when cold, and falls back to in-memory
   grouping — behind a savepoint — if the build fails or leaves it unusable.

6. **Prefilter.** `_similar` gained a length bound and difflib's `real_quick_ratio`
   / `quick_ratio` bounds, rejecting only pairs that provably cannot reach the
   threshold. Predicate unchanged, pinned by a differential test; cold build 5.8x
   cheaper.

### Measured (2000 distinct merchants / 6000 transactions)

| path | seconds |
|---|---|
| original code, no prefilter | 20.39 |
| in-memory with prefilter | 3.50 |
| one-time index build | 3.85 |
| **warm page load (indexed)** | **0.06** |
| quiet sync index update | 0.018 |

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

## Deferred work

- [#45](https://github.com/honerlaw/financials/issues/45) — prune `merchant_group_keys`
  rows orphaned by removed transactions (priority: low).
- [#46](https://github.com/honerlaw/financials/issues/46) — `merchant_key` is derived by
  two hand-written implementations that must stay in lockstep (priority: low).
