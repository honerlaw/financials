# Scratchpad: 2026-11-16-reconnect-stale-db-connections

> **Ephemeral working memory.** Most of what lands here is noise — small
> decisions that don't matter, dead ends, momentary confusion. At feature
> completion, run `minerva:promote`: significant items get promoted to
> `.minerva/knowledge/`, `proposal.md` gets updated to match reality, and
> the raw scratchpad is archived.

## Decisions 2026-11-16
- [solo] pre-flight: no collision. No local in-flight units, remote branches all belong to merged units, no open PRs; peer sessions not messaged (no authorization)
- [solo] open-issue match: no match. 7 open followup issues, none on DB connections or the scheduler; nearest is #34 (sync drops unknown account_id), which is adjacent
- [solo] scope check: one unit, one PR (tier: solo predicate. One config block in app/__init__.py plus tests, additive, no new public interface, no knowledge conflict; parallel wave)
- [reviewed — clean] approach: A, pool_pre_ping + pool_recycle (tier: reviewer. Dominance over B was in doubt; parallel wave). The Skeptic accepted and said A and B are complementary, B deferred rather than wrong; the proposal wording now says so. Noted, not load-bearing: mid-transaction drops are not covered; avoid private pool attributes in tests. Rejected: B (digest despite sync failure; 016 d5 tension, unobserved failure), C (job retry; redundant, 033 rollback care)
- [reviewed — clean] whole-proposal: Skeptic accepted (tier: reviewer; parallel wave; no restart, since approach and scope were unchanged). Adopted as editorial wording: Goal narrowed to checkout-time staleness with mid-transaction drops out of scope; criterion 1 asserts config not private attributes; criterion 2 uses a tmp_path DB; criterion 4 states the SQLite-stands-in-for-Postgres limit (033/034). The Skeptic verified on 2.0.54 that criterion 2 is achievable: ProgrammingError without pre-ping, success with it
- [reviewed — clean] completion verification: Verifier reproduced all 4 criteria (tier: reviewer floor; no interface change beyond the approved one). Gap noted: its scratch-copy flip-the-default run was denied by permissions, so the negative check rests on the author's run in Work notes plus code reading
- [solo] review triage: 1 FIX / 0 SUGGEST / 0 IGNORE (tier: default-solo row; the single finding had a reproduced failure scenario and a small fix, so it had no second defensible disposition). FIX: pool_recycle on in-memory SQLite StaticPool empties the test DB under a future freeze_time
- [solo] replan-vs-FIX: not convened. The FIX keeps the approach (pre-ping + recycle) and only narrows where recycle applies; no criterion changes
- [solo] promote partition: PROMOTE 1 (the bug entry, already written as criterion 4 and updated for the FIX) / MERGE 1 (final shape into proposal Approach) / DISCARD rest / TODO 1 (default-solo row; no entry had two defensible buckets)
- [solo] TODO disposition: "send the digest despite a failed sync" goes to a knowledge note (already in the bug entry's Limits), not an issue. It fails the bar: an unobserved failure, not critical/high, and it needs its own design (a staleness label per 016 d5)

## Work notes
- Fix: `SQLALCHEMY_ENGINE_OPTIONS={'pool_pre_ping': True, 'pool_recycle': 1800}` in create_app's config.update block.
- Criterion 2 negative check: temporarily set the shipped default to `pool_pre_ping: False`. `test_create_app_pings_and_recycles_pooled_connections` and `test_a_pooled_connection_closed_behind_the_pool_is_replaced[True]` both FAILED (2 failed, 8 passed), then passed again after the restore. The `[False]` parametrization is a permanent control that pins the failure mode (DBAPIError).
- The behavioural test's passing case uses create_app's own defaults (no override), so it guards the shipped config, not a test-local one.
- Full suite: 599 passed.
- Observation for the reference memory: `doctl apps logs --type run` DOES show APScheduler job tracebacks (it was where this bug was found). The memory saying it is "nearly useless" is wrong for job failures.

## Review triage 2026-11-16
1. FIX (medium). app/__init__.py: pool_recycle reached the `sqlite:///:memory:` StaticPool. A freeze_time far ahead makes the one connection look old; it is recycled and the next query raises `no such table`. Fixed: `_engine_options(uri)` gives in-memory SQLite pre-ping only, chosen after the config override via setdefault. Tests: `test_in_memory_sqlite_is_pinged_but_never_recycled` (2 URIs) and `test_in_memory_test_database_survives_a_clock_frozen_far_ahead`. Negative check: with recycle re-applied to in-memory, all 3 FAILED (the freeze test with `no such table: institutions`), then passed after the restore. Full suite: 602 passed.
- Reviewer cleared: options reach the engine (Flask-SQLAlchemy 3.1.1 reads the key at init_app, then merges its own SQLite poolclass/connect_args); psycopg2 is_disconnect lists "SSL SYSCALL error: EOF detected"; no other caller sets the key; scheduler thread checks out per app context; no stale docs.
