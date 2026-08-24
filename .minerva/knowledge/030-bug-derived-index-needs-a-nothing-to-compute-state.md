# A derived index must distinguish "not computed yet" from "nothing to compute"

**Date**: 2026-08-24
**Type**: bug
**Summary**: One transaction whose merchant name normalized to nothing kept `merchant_key` NULL, which the index read as outstanding work — making the index permanently unusable and sending every page load down the O(n²) path it was built to remove.

**Context**: .minerva/work/2026-08-24-merchant-group-index

## Context

The merchant-group index ([[029-decision-merchant-grouping-precomputed-at-sync]])
computes `transactions.merchant_key` lazily: the migration adds the column as
NULL, and `backfill_missing_keys()` fills it in, because `normalize_merchant` is
Python and cannot run inside a SQL migration. `is_index_usable()` therefore
treats a NULL key as "this row has not been processed yet — the index is not
ready".

The first implementation wrote `grouping_key(txn) or None`.

## Finding

Some transactions have no groupable merchant at all: a purely numeric memo, a
description that normalizes to zero letters, no `merchant_name` and no useful
`name`. For those, `grouping_key` correctly returns `''` — and `or None` turned
that into NULL.

NULL then meant two different things, and the index could not tell them apart:

- *not processed yet* → run the backfill, then the index is ready.
- *processed; there is genuinely nothing here* → the backfill will never change
  this row.

So a single such transaction made `is_index_usable()` return False forever. Every
page load attempted a rebuild, the rebuild changed nothing, and the request fell
through to the full in-memory grouping. The result was **strictly worse than
before the feature existed** — a failed rebuild *plus* the original quadratic
scan, on every request, for every merchant rather than just the offending one.
Nothing surfaced it: the page was correct, only slow.

The fix is a sentinel: store `''` for "processed, nothing to group", reserve NULL
for "not computed", and exclude `''` everywhere the index asks what is
outstanding. The in-memory grouper already dropped these rows rather than
grouping them, so behaviour matches.

Writing the regression test immediately exposed a second instance of the same
mistake in `is_index_usable`'s own query, which had been fixed in
`_unindexed_keys` but not there.

## Implications

- Any lazily-computed derived column needs three states, not two: computed,
  not-computed, and not-applicable. Collapsing the third into the second makes an
  unsatisfiable precondition, and the symptom is silent degradation rather than
  an error.
- A cache whose "not ready" path is more expensive than having no cache at all
  should say so out loud. This one falls back silently; the fallback logs only
  when a build actually raises.

## Related

- [[029-decision-merchant-grouping-precomputed-at-sync]] — the index this bug was found in
- [[031-pattern-version-stamp-must-invalidate-derived-inputs]] — the sibling invalidation bug found in the same review
