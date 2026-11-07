# Proposal: group-by-member-prefix

**Date**: 2026-11-07
**Status**: Implemented

## Goal
A name key that today's rules match to no group can still join one, when its leading words are a **member key** of that group. A member key is a name key already assigned to the group, at least `MEMBER_PREFIX_MIN_LENGTH` characters long, that is not merely a prefix of the group's representative.

The case this targets is a card network appending a city and country to a descriptor whose plain form already joined the group, e.g. `IN *ACME WIDGETS` → `IN *ACME WIDGETS ANYTOWN USA`. The rule is the same in both grouping paths, the in-memory grouper and the persisted index.

It does **not** cover a suffixed key whose plain form never became a member of that group:
- **Plain descriptor only on enriched rows.** Those rows group by merchant name, so the plain descriptor never becomes a key in the group.
- **Plain key is a prefix of the representative.** The hub guard excludes it. Example: an entity group whose representative is the longer `acme widgets anytown`, which the plain `acme widgets` joined by reverse prefix. `acme widgets springfield usa` then stays split.

A user rule still covers both.

## Why
The user found that a monthly payee showed as "Inactive" on /recurring.
- The payee is paid through a payment facilitator, and Plaid enriched the merchant name on most of its rows.
- Its newest charge came through with no merchant name and with a city and country suffix on the descriptor.
- That charge landed in a one-row group of its own, so the stream looked lapsed.

The mechanism is in grouping: `app/subscriptions.py::_group_transactions`, and `app/merchant_groups.py::update_index` / `_match_name`. A name key is compared **only with each group's representative key** (`group[0]` / `canonical_key`):
- The representative came from the enriched merchant name (`acme widgets`).
- An earlier un-enriched row (`in acme widgets`) had joined by fuzzy ratio.
- The suffixed key (`in acme widgets anytown usa`) does not extend the representative, and it is too long for the fuzzy ratio. So it starts a new group, even though a key **already in the group** is an exact word-prefix of it.

`_similar` already treats a ≥5-character prefix of the representative as a match ("NETFLIX" vs "NETFLIX LOS GATOS CA"). The gap is only that keys which joined later are never consulted.

A local replay of production data (not committed) found only correct joins: the same business under a suffixed descriptor. In it, the reported payee's suffixed key joined its group through a live member key. The replay has two limits:
- It was name-only, because the local cache holds no `merchant_entity_id`s.
- It compared the old and new rules on a cold, sorted grouping, not the production index (built incrementally) against a rebuild.

The user has already worked around the reported case with a rule. This change fixes the same shape for other merchants.

No production names, amounts or counts are recorded here, and all fixtures are fictional (the repo is public).

## Approach (A — member-key word-prefix join in both paths)
- **The rule.** It applies only to a **name key** (never an `entity:` key) that today's `_similar` matches against no group's representative.
  - Take the key's word prefixes, longest first: every token but the last, then one fewer, and so on.
  - Use the first prefix that is at least `MEMBER_PREFIX_MIN_LENGTH` = 5 characters long (counting spaces, i.e. `len(' '.join(tokens[:n]))`) and is a **member key**. The key joins that member's group.
  - Otherwise the key opens its own group, as today.
  - The 5 is deliberately aligned with `_similar`'s prefix minimum and `DESCRIPTOR_MIN_LENGTH`.
- **Member keys.** A member key is a **name key assigned to the group** that is neither the group's representative nor a prefix of it (`representative.startswith(key)`).
  - Representatives are redundant as members: `_similar`'s `startswith` branch already matches a representative that is a word-prefix of the key.
  - Excluding prefixes of the representative is the **hub guard**. A bare `amazon` that joined an `amazon prime` group by reverse prefix must not pull in every `amazon …` key.
  - A name key belongs to exactly one group (`MerchantGroupKey.key` is unique, and in memory keys are dict keys), so the member dict has no collisions.
  - Matching is on word boundaries only: `acme widget` never pulls in `acme widgetry`.
- **In-memory path** (`_group_transactions`). A dict from member key to group is filled as name keys join or open groups, subject to the guard.
  - Keys are processed in sorted order, and a word prefix always sorts before its extensions. So within one pass a member is present before its extension is processed.
  - Only live rows reach this path.
- **Indexed path** (`update_index`).
  - The member dict is built **after** the "nothing new" early return, so a quiet sync costs no extra query.
  - It holds the name keys in `MerchantGroupKey` that have **at least one live transaction** (`removed` false), each with its group's `canonical_key` for the guard. `MerchantGroupKey` keeps every key ever seen, including keys of removed rows and keys left behind by a merchant-name change. Restricting members to live keys makes the indexed member set match the in-memory one on a cold build or rebuild, so a removed row's key cannot bridge a join there. Incremental divergences remain (see Known consequences).
  - **Every** new live name key assigned in the pass is added as a member, subject to the guard. That covers keys placed by `_match_name`'s fuzzy match, keys placed by the member rule, and keys that open a group; the guard drops those, because each is its own group's representative. On a cold build `MerchantGroupKey` is empty, so these same-pass additions are the whole member set.
  - Entity keys keep today's `_match_name(..., allow_entity_groups=False)` and never use the rule, so two entity ids never merge (knowledge 032).
- **Shared helpers.** Pure functions in `app/subscriptions.py` serve both paths, so the rule cannot drift between them:
  - `member_prefix_match(key, members)` returns the group handle or None;
  - `is_member(key, representative)` applies the guard.
- **Cost.** At most one dict lookup per word of a key, plus one linear query when the index has new keys. There are no new fuzzy comparisons, so knowledge 029's bound holds.
- **Rebuild.** `GROUPING_ALGO_VERSION` goes from 1 to 2.
  - The existing version-stamp mechanism (knowledge 031) nulls and recomputes `merchant_key` and rebuilds the index once. That happens on the first `/recurring` load after deploy or on the next sync, whichever comes first.
  - `normalize_merchant` and `grouping_key` are unchanged, so recomputed keys are identical.
  - The rebuild is required. Assigned keys are never rematched, so only the rebuild repairs the production split.
  - Cost: the full fuzzy pass takes under a second on a corpus the size of the production replay. The per-row key recompute (one UPDATE per transaction) and one query per entity key likely dominate, at roughly tens of seconds — well under the 120 s worker timeout. The same cold-build path already ran in production when the index first shipped.
- **Documentation updated in this unit:**
  - the comment above `GROUPING_ALGO_VERSION`: the grouping rule is one of the things to bump for;
  - the `app/merchant_groups.py` module docstring ("compared against the frozen canonical keys");
  - the `MerchantGroup` docstring in `app/models.py`;
  - the `_group_transactions` docstring and its inline comment.

  Promote records the rule and links it to knowledge 029.
- **Unchanged code:** `normalize_merchant`, `grouping_key`, `FUZZY_THRESHOLD`, `_similar`, `merge_by_descriptor`, detection and rules. Their *inputs* change wherever groups change (see Known consequences).

### Alternatives considered
- **B — request-time descriptor-prefix merge in `merge_by_descriptor`.**
  - It needs no index rebuild.
  - But that merge requires date-disjoint groups. A payee whose descriptor alternates between the plain and suffixed forms would overlap and stay split, so the fix would undo itself the first time both forms appear.
  - It also moves grouping logic into a second place.
- **C — strip payment-facilitator prefixes (`IN *`, `SQ *`, `TST*`) in `normalize_merchant`.**
  - It fixes this case through the existing representative-prefix rule.
  - But it changes every stored `merchant_key` and the identity of every facilitator-routed merchant.
  - It is a hand-kept list, and it misses the same failure for non-facilitator descriptors.
- **E — also treat each group's normalized descriptors as members.**
  - It would cover the plain-only-on-enriched-rows case.
  - But descriptors carry generic leading phrases (`paypal …`, `online transfer …`, `zelle payment …`). Those would become hubs joining unrelated payees.
  - Grouping keys are what grouping already trusts.
- **D — leave it to user rules.** This already works for the reported payee, but the user has to notice each case.

## Success criteria
Every fixture is fictional and asserts its own `_similar` preconditions, so a test cannot pass with the rule removed or its bound deleted.

1. **In-memory grouping tests:**
   - **Target case.** Assert that `_similar('acme widgets', 'in acme widgets')` is True and `_similar('acme widgets', 'in acme widgets anytown usa')` is False. Then enriched rows ("Acme Widgets"), an un-enriched `IN *ACME WIDGETS` row and an un-enriched `IN *ACME WIDGETS ANYTOWN USA` row form **one** group. Cover this with the enriched rows both as a name group and as an entity group.
   - **Minimum length.** Use an entity representative `xabcd`, which name key `abcd` joins by ratio without being a prefix of it. Key `abcd xyz` then stays separate. A test with `MEMBER_PREFIX_MIN_LENGTH` patched to 0 shows that it would join.
   - **Word boundary.** Use a representative that a member `in acme widget` joins by ratio without being a prefix of it. Key `in acme widgetry bar` does not join through that member.
   - **Hub guard.** A name key that is a prefix of its group's representative is not a member. Example: `amazon` in an `amazon prime` entity group, so `amazon fresh delivery` does not join through it.
   - **Entity keys never use the rule** (incremental, because entity keys are handled before name keys in a pass). Build an index whose name group has the member `in acme widgets`, then sync an entity whose representative name is `in acme widgets anytown usa`. It does not join that group.
2. **Indexed path** (`tests/test_merchant_groups.py`):
   - **Partition parity.** On the tested fixtures, a cold-built index splits the corpus into the same partition as `_group_transactions`. Three pre-existing differences can still split them on other corpora; they occur with the rule off too (see Known consequences).
     - The comparison is not on detector output. It compares groups as sets of `(date, amount, description)` tuples, or as transaction ids queried through `MerchantGroupKey`; detection rows carry no id.
     - The corpus includes the target case, and a **removed** row whose key would be the member prefix. Neither path joins through that removed key.
   - **Incremental.** After the index is built, a newly synced suffixed key joins the existing group.
   - **v1 → v2 regroup** (knowledge 031):
     - Build the index with the rule disabled (monkeypatched) and `app.merchant_groups.GROUPING_ALGO_VERSION` patched to 1. Assert the suffixed key is in its own group.
     - Restore the rule and the real `GROUPING_ALGO_VERSION` (2), then run `update_index()`. Assert that one group now holds both.
3. `GROUPING_ALGO_VERSION == 2`, and the four documentation spots above are updated.
4. `uv run pytest` passes, including the parity tests, the quiet-sync query-count test (`QUIET_SYNC_SELECTS`) and the differential `_similar` tests.
5. **After deploy**, report to the user only:
   - The first `/recurring` load succeeds; this is the request that runs the rebuild.
   - Preview a **candidate** rule on the reported payee that outranks the saved rule. If the saved rule is unranged, give the candidate an amount range covering the payee's charges; otherwise give it an amount range **and** a strictly longer pattern. The candidate's "Taken from" shows a **single** merchant group.
   - Give the counted total before and after.
   - If the payee is still split, say so. The saved rule keeps it counted meanwhile, and the cause is investigated as a follow-up.

## Known consequences
- **The rule can re-home keys it never matches directly.** When a key that used to open its own group G2 now joins G1, G2's representative no longer exists. A later key that matched G2 only by fuzzy ratio, and that has no member word-prefix, now opens a group of its own or matches elsewhere. Example: the same suffixed descriptor routed through two facilitators.
- **Grown groups can stop a descriptor merge, so one bill can count twice.**
  - Scenario: group A holds an enriched name plus an un-enriched plain row. A later Plaid rename gives group B the same descriptor. A suffixed row dated in B's period now joins A.
  - A then overlaps B in time, and `merge_by_descriptor` refuses date-overlapping groups. A and B stay two streams.
  - The same already happens today for an un-enriched plain row that lands in the renamed period. The rule extends it to suffixed rows.
- **The rebuild regroups everything once, in sorted order.**
  - The persisted index is first-come-wins (knowledge 029), so drift accumulated since it was built can also move groups.
  - The production change may be larger than the rule alone, and the name-only replay could not measure that.
  - Rules claim rows, not groups, so they are unaffected.
- **The rebuild runs once, possibly inside a request.**
  - It reloads every transaction. It runs in a savepoint with the in-memory fallback.
  - A worker killed on timeout would roll back and retry on the next load. The measured fuzzy-pass cost and the earlier production cold build make that unlikely.
  - Criterion 5 checks the first load.
- **Incremental order still matters.**
  - If a suffixed key syncs before its plain form ever appears, the index keeps them split until the next rebuild, while the in-memory path merges them.
  - If a member's rows are later removed after its extension joined through it, the index keeps the join while the in-memory path splits it.
  - Both are within 029's accepted first-come-wins divergence. The parity tests cover cold builds.
- **Cold-build parity is not total, and that predates this change.** Three differences, all present with the rule off (found by fuzzing about 4,400 random corpora in code review):
  - keys found only on removed rows still open groups and fuzzy-match in the index, but not in memory;
  - two entity groups with the same representative name collide in `canonical` (the last one wins in the index, the first in memory);
  - `_representative_name` drops empty names, while `_group_key` does not.
- **A member key that joined by fuzzy ratio also pulls in its word-extensions.** The 5-character minimum, the word boundary and the hub guard bound this. The guard covers only exact prefixes of the representative.

## Open Questions
- None.
