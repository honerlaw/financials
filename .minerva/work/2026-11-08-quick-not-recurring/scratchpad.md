# Scratchpad: quick-not-recurring

> **Ephemeral working memory.** Most of what lands here is noise — small
> decisions that don't matter, dead ends, momentary confusion. At feature
> completion, run `minerva:promote`: significant items get promoted to
> `.minerva/knowledge/`, `proposal.md` gets updated to match reality, and
> the raw scratchpad is archived.

## Decisions 2026-11-08
- [reviewed — clean] scope check: one unit, one PR, no phases (tier: reviewer — new route fails solo's no-new-interface clause; parallel wave). Skeptic's approach-level concerns (guard keyed on grouping_key) carried to the approach gate
- [reviewed — folded] approach: A kept; guard changed from grouping-key containment to exact row-set equality against the server-recomputed stream, plus idempotent re-post, pattern in notice, future-matches title, ?marked int parse (tier: reviewer — introduces a new route, no existing consumer; parallel wave). Rejected: B no guard, C per-stream dismiss table, D inline per-row preview, A′ key containment
- [rechecked — residual folded] approach: R1.7 essential-mark-survives test and R2.7 action preserved partially addressed; folded the test, Decimal split_amount compare, action filter on the already-marked lookup, and a consumer check for the new `rows` key
- [reviewed — clean] whole-proposal (restart): re-reviewed after the approach fold rewrote Success criteria; notes (dedupe while stream still found → candidate loses rows to the identical saved rule, so it falls back to the form; autoescape) not load-bearing (tier: reviewer; parallel wave restart)
