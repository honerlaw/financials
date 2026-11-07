# A name key joins a group through a member key that is a word prefix of it

**Date**: 2026-11-07
**Type**: decision
**Theme**: merchant-grouping
**Summary**: Grouping now also joins a name key to the group of a **member key** that is a word prefix of it (≥5 chars; never the representative or a prefix of it; live keys only in the index), so a descriptor with a city/country appended joins the group its plain form already joined; `GROUPING_ALGO_VERSION` 2 rebuilt the index once.
**Context**: .minerva/work/2026-11-07-group-by-member-prefix (see git history if the worktree has been cleaned up)

## Context

Both grouping paths compared a new name key only with each group's representative: `group[0]` in `_group_transactions`, and `canonical_key` in `update_index` / `_match_name`. That breaks in a specific chain:
- A group's representative comes from Plaid's enriched merchant name (`acme widgets`).
- An un-enriched row (`in acme widgets`, with the payment-facilitator prefix) joins it by fuzzy ratio.
- A later un-enriched row with a city and country appended (`in acme widgets anytown usa`) neither extends the representative nor reaches the ratio, so it opens a one-row group.

The bill's newest charge then sits in that other group, and the stream reads as Inactive.

## Finding

1. **The rule.** It applies only to a name key that matches no representative. Its word prefixes are tried longest first. The first one that is at least `MEMBER_PREFIX_MIN_LENGTH` = 5 characters (spaces counted) and is a member key places the key in that member's group. The rule lives in `app/subscriptions.py::member_prefix_match`, and both paths call it.
2. **Member keys.**
   - A member key is a name key assigned to the group, provided `is_member(key, representative)` holds, i.e. the representative does not start with it.
   - Representatives are redundant as members: `_similar`'s prefix branch already covers them.
   - Prefixes of the representative are excluded so they cannot become hubs: a bare `amazon` inside an `amazon prime` group must not pull in every `amazon …` key.
   - Matching is on word boundaries only.
3. **The index's members are live keys only.** `merchant_group_keys` keeps every key ever seen, including keys of removed rows and keys left behind after a merchant-name change. The in-memory grouper never sees those keys, so in the index `_live_members` admits only keys with a non-removed transaction. Every live name key assigned in a pass becomes a member, whether it was placed by fuzzy match, by the rule, or by opening a group (the guard drops the last). The dict is built after the quiet-sync early return, so a quiet sync still runs 3 SELECTs.
4. **Entity keys never use the rule.** Knowledge 032 holds. The rule only ever places a new name key and never merges two existing groups.
5. **Version 2.** The bump rebuilt the index once. The test `test_version_bump_regroups_an_index_built_without_the_rule` changes the real rule and asserts the grouping changes, as knowledge 031 requires.

## Implications

- **The change is not purely additive.** A key that used to open its own group G2 now joins G1, so G2's representative no longer exists. A later key that matched only that representative by ratio may open a new group or land elsewhere.
- **A grown group can block `merge_by_descriptor`, so one bill can count twice.** A suffixed row joining an older group can make it overlap a renamed group that shares its descriptor, and the merge then refuses.
- **The rule does not cover two cases.** One is a suffixed key whose plain form only ever appeared on enriched rows; those rows group by merchant name. The other is a plain key that is a prefix of the representative. User rules cover both.
- **Incremental order still matters, within knowledge 029's first-come-wins divergence.**
  - If the suffixed key syncs before its plain form ever appears, the two stay split until a rebuild.
  - If a member's rows are removed after its extension joined through it, the join persists.
- **Cold-build parity between the paths is not total, and this predates the rule.** Fuzzing about 4,400 random corpora found divergences only from three existing causes, all present with the rule off:
  - keys from removed rows still open groups and fuzzy-match in the index;
  - two entity groups with the same representative name collide in `canonical`;
  - `_representative_name` drops empty names, while `_group_key` does not.

## Related
- [[029-decision-merchant-grouping-precomputed-at-sync]] — extends its matching. Assigned keys are still never rematched, and the cost is one dict lookup per word.
- [[032-constraint-plaid-entity-ids-must-never-fuzzy-merge]] — entity keys never use the rule.
- [[031-pattern-version-stamp-must-invalidate-derived-inputs]] — the version 2 rebuild and its rule-changing test.
- [[2026-11-07-decision-merge-groups-renamed-by-plaid]] — a grown group can block a descriptor merge.
