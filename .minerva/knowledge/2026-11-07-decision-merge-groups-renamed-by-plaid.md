# Merchant groups that share a card descriptor merge at detection time when Plaid renames a merchant

**Date**: 2026-11-07
**Type**: decision
**Theme**: recurring-detection
**Summary**: `merge_by_descriptor` joins date-disjoint, same-side groups sharing a descriptor, unless a bucket holds 2+ entity ids.
**Context**: .minerva/work/2026-11-06-descriptor-merge (see git history if the worktree has been cleaned up)

## Context

Grouping keys on Plaid's `merchant_entity_id`, falling back to the fuzzy-normalized
`merchant_name`. Plaid's merchant-name enrichment can change partway through a merchant's
history, while the transaction `name` (stored as `description`; for card issuers such as AmEx
this is the card-network descriptor) stays the same. When that happens one monthly bill splits
in two. The old-name group looks lapsed, so it is inactive and not counted. The new-name group
has too few charges to be a stream. The bill drops out of the /recurring total entirely.

## Finding

1. **A second grouping signal, applied after grouping.** `subscriptions.merge_by_descriptor(groups)`
   runs once per request at the top of `detect_subscriptions_from_groups` and
   `bills.detect_recurring_from_groups`, so both the indexed path and the in-memory path see merged
   groups. The persisted index (knowledge 029) still stores the pre-merge grouping, so nothing
   changed in the schema, `GROUPING_ALGO_VERSION` or `grouping_key`.
2. **Merge only what is clearly a rename.**
   - Groups are bucketed by their dominant `normalize_merchant(description)`: the most common
     value, with ties going to the smallest. Matching is by exact equality only. Fuzzy matching
     here would bring back the per-request quadratic cost that 029 moved to sync time.
   - Descriptors shorter than 5 characters never merge.
   - A bucket whose groups carry two or more distinct entity ids merges **nothing**. Two entities
     are two merchants (032), and a group with no entity id cannot be assigned to one of them.
   - Charges and deposits never merge, using the signed median that `_build_stream` uses.
   - A side merges only if **every pair** of its groups is date-disjoint, and a shared day counts
     as overlap. Greedy accumulation was rejected because two short groups nested inside a
     concurrent long group could merge with each other.
3. **Deterministic and pure.** Groups are ordered by a total key: dates, display name, size,
   then the sorted descriptions, amounts and entity ids. Input lists are copied and never mutated.
   The result is the same under any permutation of the input.

## Implications

- The rule is strict on purpose. If a transition month has charges under both names, or Plaid
  re-enriches only some of the old rows, the date ranges overlap and the groups stay split. That
  is the old behaviour, and it never produces a false merge. No manual merge/unmerge override exists.
- Two one-off purchases a year apart under one descriptor can turn into an annual stream. Annual
  streams are listed but never counted, so this is accepted noise.
- For an issuer whose `description` equals the enriched `merchant_name`, the merge does nothing.
- **Test fixtures:** `FakeTxn` in `tests/test_subscriptions.py` and `tests/test_bills.py` sets
  `description` to `merchant_name` by default. A shared placeholder descriptor such as the old
  `'CHARGE'` makes unrelated sequential fixture merchants merge. Any new fixture that shares a
  descriptor across merchants will be merged.

## Related
- [[029-decision-merchant-grouping-precomputed-at-sync]] — the index stays pre-merge; the merge is linear, so 029's cost constraint holds
- [[032-constraint-plaid-entity-ids-must-never-fuzzy-merge]] — extended: a bucket holding two entity ids merges nothing
- [[003-decision-subscriptions-cadence-only-detection]] — cadence detection unchanged; it now runs on merged groups
- [[2026-11-06-decision-recurring-page-and-income-rule]] — the /recurring page whose totals this corrects
