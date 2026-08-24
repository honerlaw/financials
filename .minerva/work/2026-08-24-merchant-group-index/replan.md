# Replan: merchant-group-index

## 2026-08-24 — success criteria C2 and C6 did not say what they meant

### Original plan

- **C2**: "A sync that changed nothing performs one indexed query and no matching work."
- **C6**: "The in-memory fallback path remains reachable and correct when the index
  is absent", evidenced by `test_cold_index_falls_back_and_warms`.

### What changed

A completion-verification pass measured both claims instead of reading them.

- **C2 was wrong about the number.** A SQLAlchemy query counter recorded **3**
  SELECTs on a quiet sync (`_stored_algo_version`, `backfill_missing_keys`,
  `_unindexed_keys`), not one. The property the criterion existed to protect —
  no fuzzy matching, and a cost that does not scale with merchant count — holds
  and is met. The number was written before the implementation existed and
  never checked.

- **C6 was evidenced by the wrong test.** `test_cold_index_falls_back_and_warms`
  asserts `used_index is True`: it exercises warm-on-demand, not the fallback.
  The fallback branch had no test at all.

- **And the fallback was actually broken for the case that matters.** Reviewing
  the fix surfaced a defect neither criterion had contemplated:
  `groups_for_detection` caught the exception and immediately re-queried, with
  no savepoint and no rollback. On Postgres a statement failing inside an open
  transaction leaves it aborted, so the fallback's own query would raise and the
  page would go from slow to broken — precisely the outcome the fallback exists
  to prevent. The same hazard sat in `_sync_institution`, where a poisoned
  transaction would then fail the closing `db.session.commit()`, discarding the
  transactions already upserted, losing the SyncLog row, and killing the
  remaining institutions in the loop. `_create_account_if_missing` already
  documents this exact failure mode and solves it with a savepoint; the new code
  did not follow that precedent.

  The test suite could not have caught it: SQLite tolerates statement failure
  inside a transaction where Postgres does not. Verified by removing the
  savepoint and re-running — the test still passes on SQLite.

### New plan

1. Restate C2 as the property rather than the number: "A sync that changed
   nothing performs a small constant number of indexed queries (3) and no fuzzy
   matching, with the constant independent of corpus size."
2. Pin it with `test_quiet_update_cost_does_not_grow_with_the_corpus`, which
   asserts the count exactly (`QUIET_SYNC_SELECTS = 3`, not a slack bound that
   would let a 3→4 regression pass) **and** asserts it is unchanged after the
   corpus grows by 200 merchants. Pinning the invariant was chosen over
   minimising the constant: three O(1) round trips is not a cost worth
   collapsing, and the thing worth defending is that it stays O(1).
3. Wrap the index update in `db.session.begin_nested()` in both call sites,
   matching `_create_account_if_missing`'s precedent.
4. Add `test_build_failure_falls_back_to_in_memory_grouping` (mocked raise),
   `test_unusable_after_successful_build_still_falls_back` (build succeeds,
   index still unusable), and `test_sql_failure_during_build_leaves_the_session_usable`
   (a real failing statement, with the session asserted usable afterwards).

C6's original wording stands; it was the evidence that was wrong, not the goal.
