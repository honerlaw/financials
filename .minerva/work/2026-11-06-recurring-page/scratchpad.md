# Scratchpad: recurring-page

> **Ephemeral working memory.** Most of what lands here is noise — small
> decisions that don't matter, dead ends, momentary confusion. At feature
> completion, run `minerva:promote`: significant items get promoted to
> `.minerva/knowledge/`, `proposal.md` gets updated to match reality, and
> the raw scratchpad is archived.

## Decisions 2026-11-06
- [escalated to user] intake design (pre-auto, minerva:propose): user chose new /recurring page over extending /bills; income vs expenses; split counted/not-counted; collapsed not-counted grouped by reason; income P25; paycheck biweekly
- [user-directed] approach: new /recurring page (user picked it over extending /bills in place during propose intake)
- [reviewed — clean] scope check: single unit, one PR (tier: reviewer — multi-file, removes two routes so not additive; Skeptic accept, noted income-classification, single-pass and test-migration concerns, carried to whole-proposal; parallel wave)
- [reviewed — folded] whole-proposal: folded test migration incl. query-count guard, INCOME-category gate for income (uncategorized not counted), single-pass detect_recurring_from_groups, income total sums rounded rows, left-over iff counted income ≥1, 302 not 301, status summary kept, no badge on not-counted rows, estimator labels (tier: reviewer — not provably small; parallel wave)
- [rechecked — residual folded] whole-proposal: item 4 partially addressed (26/12 not pinned through the route) — added route test with biweekly INCOME_WAGES stream; also added unauthenticated-redirect test
