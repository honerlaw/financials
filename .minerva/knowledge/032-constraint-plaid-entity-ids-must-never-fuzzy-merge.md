# Two distinct `merchant_entity_id`s must never merge, however alike their names

**Date**: 2026-08-24
**Type**: constraint
**Summary**: The persisted merchant index could merge two different Plaid entity ids whose display names fuzzy-matched, while the in-memory grouper never compares entity groups against each other — so the same data produced different subscriptions depending on whether the index was warm.

**Context**: .minerva/work/2026-08-24-merchant-group-index

## Context

Merchant grouping runs two ways ([[029-decision-merchant-grouping-precomputed-at-sync]]):
`_group_transactions` in memory, and `update_index` against the persisted tables.
Both implement the same rule — group by `merchant_entity_id` when Plaid supplies
one, else by fuzzy-matched normalized name.

A group's `canonical_key` must be a normalized **name**, never the raw
`entity:<id>` string, or a bare-name charge can never join the entity group for
the same merchant and the stream splits in two. Storing the name there is what
created the opening for this bug.

## Finding

Once an entity-derived group's canonical key is a name, a *second* entity id
whose representative name fuzzy-matches will merge into it. The in-memory path
never does this: it seeds one group per entity id and only ever merges *name*
keys into them, never comparing entity groups against each other.

The divergence is not cosmetic. Two entity ids both displaying as "Amazon", two
charges each on interleaved months:

- in-memory → two 2-charge groups, neither clears `MIN_OCCURRENCES` → **no
  subscription**
- indexed → one 4-charge group → **a monthly Amazon subscription appears**

A subscription that exists or not depending on cache warmth. This is outside the
accepted first-come-wins-vs-sorted-order divergence, which only ever affects
which of several similar groups a name lands in.

`merchant_groups.from_entity` now records the provenance. An entity key may join a
name-derived group — Plaid starting to supply an entity id for a merchant already
seen without one must not split a live stream — but never another entity's group.

## Implications

- **A `merchant_entity_id` is an identity assertion from Plaid, not a display
  string.** Two different ids mean two different merchants even when the names are
  identical; fuzzy matching must never be allowed to overrule that.
- Whenever the same rule is implemented twice, the divergences will not be where
  the differences were designed. Both known divergences here were found by
  differential testing the two paths against identical corpora, not by reading.
- The provenance flag is load-bearing. Dropping `from_entity` to "simplify"
  reintroduces the merge.

## Related

- [[029-decision-merchant-grouping-precomputed-at-sync]] — the two-path design this constrains
- [[003-decision-subscriptions-cadence-only-detection]] — MIN_OCCURRENCES, the threshold that turns a wrong merge into a phantom subscription
