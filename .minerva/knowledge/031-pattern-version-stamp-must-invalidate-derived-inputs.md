# A version stamp must invalidate the derived *inputs*, not just the derived output

**Date**: 2026-08-24
**Type**: pattern
**Summary**: The merchant index's algo-version rebuild deleted the groups but regrouped the stale per-row keys the old algorithm had produced — reporting a successful rebuild while reproducing exactly the grouping it existed to replace.

**Context**: .minerva/work/2026-08-24-merchant-group-index

## Context

The merchant-group index carries `GROUPING_ALGO_VERSION`
([[029-decision-merchant-grouping-precomputed-at-sync]]). The stated contract, in
the module docstring: "tuning `FUZZY_THRESHOLD` or `normalize_merchant` can never
leave a silently stale grouping behind." On a version mismatch, `update_index()`
deleted every `MerchantGroup` and `MerchantGroupKey` and rebuilt.

## Finding

The rebuild was one layer too shallow. There are **two** derived artifacts, not
one:

1. `transactions.merchant_key` — the normalized key, produced by
   `normalize_merchant`.
2. `merchant_groups` / `merchant_group_keys` — the grouping, produced by the
   fuzzy matcher over those keys.

A version bump exists *precisely because* one of those producers changed. Deleting
only the groups and regrouping the stored keys re-derives the old grouping from
old inputs, then stamps it with the new version. The rebuild reports
`rebuilt: True` and changes nothing.

Concretely: add `'autopay'` to `_NOISE_TOKENS` so `AUTOPAY NETFLIX` and `NETFLIX`
should collapse. Before the fix, rows synced earlier kept
`merchant_key='autopay netflix'`, so the rebuild produced two groups where the
in-memory path — which re-derives keys from `merchant_name` on every call —
produced one. With few enough charges per variant, each falls below
`MIN_OCCURRENCES` and the subscription disappears entirely from the indexed path.

The fix nulls `transactions.merchant_key` as part of the rebuild so the backfill
recomputes every key.

## Implications

- When invalidating a cache, enumerate every artifact downstream of the thing
  that changed. "Delete the output and recompute" is only correct when the inputs
  were not themselves derived by the code that changed.
- **A test that bumps only the version number cannot detect this.** The original
  test monkeypatched `GROUPING_ALGO_VERSION` and asserted rows were re-stamped —
  it passed against the broken code. A rebuild test has to change the actual
  algorithm and assert the *output differs*, or it only tests bookkeeping.

## Related

- [[029-decision-merchant-grouping-precomputed-at-sync]] — the index whose rebuild this corrects
- [[030-bug-derived-index-needs-a-nothing-to-compute-state]] — the sibling invalidation bug found in the same review
