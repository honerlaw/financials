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
