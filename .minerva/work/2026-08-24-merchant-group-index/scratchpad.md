# Scratchpad: merchant-group-index

> **Ephemeral working memory.** Most of what lands here is noise — small
> decisions that don't matter, dead ends, momentary confusion. At feature
> completion, run `minerva:promote`: significant items get promoted to
> `.minerva/knowledge/`, `proposal.md` gets updated to match reality, and
> the raw scratchpad is archived.

## Cross-session constraints (2026-08-24)

Session `financials-24` is doing a Bootstrap → Tailwind redesign in parallel,
scoped to `app/templates/*.html` and `app/static/*` — **no .py files**. Agreed
contract:

- Their diff is presentation-only; the `/subscriptions` and `/bills` view
  functions and the dict keys they pass to templates are mine and stay stable.
- **Do not touch `app/routes.py:261`** — `'amount_class': 'text-danger' if
  txn.amount > 0 else 'text-success'` in the `/api/transactions` payload. The
  infinite-scroll JS applies that string verbatim, and they are keeping
  `.text-danger` / `.text-success` as live class names in the new stylesheet
  precisely because routes.py is not theirs to edit. It is the one string
  coupling the two diffs. Not in this unit's scope anyway — noted so it does not
  get "cleaned up" opportunistically.
- Whoever merges first, the other rebases; no sequencing needed.

Also in flight earlier today: `financials-4d` shipped PR #35 (da2cda1) and the
knowledge reconcile #36 (adfaf78). This branch is based on adfaf78. Their diff
touched `_refresh_balances` / `_refresh_investments` bodies and added
`_create_account_if_missing`; `_upsert_transactions` and the tail of
`_sync_institution` — the two places this unit edits in sync.py — were left
untouched. `tests/test_sync.py` grew ~230 lines and its import block is the
likely conflict surface if this unit appends test cases there.

## Balanced decisions 2026-08-24

- [escalated to user] pre-flight in-flight collision: unit 2026-08-24-merchant-group-index reported in_flight=True and matched the run seed — user chose "resume the existing unit" (escalation counter = 1)
- [decided] Phase 1 gates not re-run: scope check and approach selection were answered directly by the user during the interactive propose run (single-unit scope covering /subscriptions + /bills; approach A incremental index over B full-recompute and C algorithm-fix-only), then stress-tested via minerva:grill-plan. Human decisions supersede an advisory Skeptic; re-dispatching would re-litigate settled calls.
- [decided] whole-proposal soundness: single subsystem, no public HTTP interface change, template contract unchanged (solo gate)
- [decided] entity-group canonical key = representative normalized name, not 'entity:<id>'. Caught while implementing `_assign`: storing the raw entity key means a bare-name charge ("netflix") can never fuzzy-match into the Netflix entity group, silently splitting one stream into two — each of which may then fall below MIN_OCCURRENCES and disappear from both pages. Mirrors `_group_key` in subscriptions.py. Pinned by test_name_key_joins_the_entity_group. Not treated as a load-bearing divergence: it is a refinement *within* the approved approach (the proposal did not specify what an entity group's canonical key holds), the success criteria are unchanged, and the completion Verifier gate covers it.
- [decided] entity keys are processed before name keys in update_index, mirroring how `_group_transactions` seeds its group list from merchant_entity_id before merging name keys. A name key can only join an entity group that already exists.
- [decided] a new entity key first tries to fuzzy-match its representative name into an existing group rather than always opening its own. Diverges from a cold full recompute (which would keep two entity ids with similar names separate) but prevents the bad direction: Plaid starting to supply an entity id for a merchant that already has a name group would otherwise split a live stream.

### Measured (2000 distinct merchants / 6000 transactions, sqlite in-memory)

| path | seconds |
|---|---|
| original code, no prefilter (pre-change baseline) | 20.39 |
| in-memory with prefilter | 3.50 |
| one-time index build | 3.85 |
| warm page load (indexed) | 0.06 |
| quiet sync index update | 0.018 |

~340x on a warm load versus the pre-change baseline; 5.8x of that is the prefilter alone.
- [reviewed — folded] completion verification (Verifier): C2 met=no (measured 3 SELECTs, not 1) and C6 met=partial (cited test exercised warm-on-demand, not the fallback branch). Both folded — criterion restated, three fallback tests added. Triggered Phase 2.5.
- [reviewed — folded] replan acceptance (Skeptic): verdict revise. Concern #1 (high) was a real defect, not a documentation gap — no savepoint or rollback around update_index, so on Postgres an aborted transaction would make the fallback's own query raise, and would fail _sync_institution's closing commit. Folded: begin_nested at both call sites per _create_account_if_missing's precedent, plus a real-SQL-failure test. Concern #3 (medium) folded: exact == 3 assertion plus a second corpus an order of magnitude larger, replacing the <= 4 slack bound. Concern #2 (medium) answered by pinning the O(1) invariant rather than minimising the constant. Concern #5 (low, pre-existing) recorded as a follow-up below.
- TODO (follow-up, low): `_unindexed_keys` uses `NOT IN (subquery)`, a classic anti-join pattern some planners handle poorly at scale. Currently safe — MerchantGroupKey.key is non-nullable, so the NULL-sensitivity trap does not apply — and the new query-count test measures round trips, not per-query cost, so a plan regression here would not be caught. Worth revisiting if the corpus grows.
- Verified: removing the savepoint and re-running test_sql_failure_during_build_leaves_the_session_usable still passes on SQLite. The suite's backend cannot detect Postgres aborted-transaction bugs; savepoint discipline holds by inspection and precedent, not by test. Candidate knowledge entry.

## Review triage 2026-08-24

Minerva audit (self) — 3 findings, all FIXed:
- knowledge 017 prescribes exercising a new migration in isolation (conftest uses `db.create_all()`, never Alembic, so a migration can be wrong with no test catching it). Had not been done. Ran the procedure: upgrade and downgrade both round-trip, re-verified after the `from_entity` amendment.
- knowledge 020: `_upsert_transactions` runs `_grouping_key_for` in existing sync tests, but nothing asserted the result — the write path could start storing NULL with the suite still green. Added `test_sync_writes_merchant_key_on_upsert`.
- Spec fidelity vs proposal `## Approach`: clean, all six items present.

Code review (fresh-context subagent) — 9 findings:
- [high, FIX] #1 one transaction whose merchant_key can never be computed left it NULL, which `is_index_usable` reads as outstanding work — the index would never become usable, and every page load would attempt a rebuild and then fall back to in-memory grouping. Strictly worse than before the feature. Fixed with a '' sentinel meaning "processed, nothing to group". Writing the regression test then exposed a second instance I had missed in `is_index_usable`'s own query.
- [high, FIX] #2 a version bump deleted the groups but regrouped the *stale* `merchant_key` values, reproducing the old grouping under a new stamp — a rebuild that reports success while changing nothing. Now nulls the keys so backfill recomputes them.
- [high, FIX] #3 the persisted path could merge two distinct `merchant_entity_id`s whose representative names fuzzy-match; the in-memory path never compares entity groups against each other. Two sub-threshold streams merged into one that cleared MIN_OCCURRENCES, so a subscription existed or not depending on whether the index was warm. Added `merchant_groups.from_entity`; an entity key may join a name-derived group but never another entity's.
- [medium, FIX] #4 `_representative_name` did not filter `removed`, unlike `_group_key` which only ever sees live rows.
- [medium, FIX] #9 `test_version_bump_rebuilds_exactly_once` bumped only the version number and so could not detect #2. Added `test_version_bump_recomputes_merchant_keys`, which actually changes `_NOISE_TOKENS`.
- [low, FIX] #5 duplicated fallback block factored into `_in_memory_fallback`.
- [low, SUGGEST] #6 `_grouping_key_for` (Plaid objects) and `grouping_key` (Transaction rows) are two hand-written implementations of one rule. A change to either that is not mirrored silently splits merchants. Held: unifying them means passing Plaid objects into a pure module or building a shim type, both worse than the comment plus the new write-path test. Revisit if a third caller appears.
- [low, TODO] #7 keys belonging only to removed transactions are indexed and never pruned — permanent debris in `merchant_group_keys`, not a correctness bug.
- #8 migration: no issues. #10 count discrepancy was a test added after the brief was written.

All three high findings were verified to fail against the pre-fix code and pass after, by reverting each fix in isolation.

No replan-vs-FIX gate: these are defects in executing the approved approach, not divergence from it. The approach section still describes what shipped.
