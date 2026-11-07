# Scratchpad: calendar-month-cadence

> **Ephemeral working memory.** Most of what lands here is noise — small
> decisions that don't matter, dead ends, momentary confusion. At feature
> completion, run `minerva:promote`: significant items get promoted to
> `.minerva/knowledge/`, `proposal.md` gets updated to match reality, and
> the raw scratchpad is archived.

## Decisions 2026-11-07
- [solo] scope check: one unit, one PR (tier: solo predicate — one private function plus a helper in app/subscriptions.py and tests; additive; no new public interface; parallel wave)
- [panel — 3/3 accept, 3 with fixes] approach: A, calendar-month regularity inside the monthly bucket, over B′ (per-gap ±13) and C (GAP_REGULARITY 0.6) (tier: panel — knowledge-tension doubt with 003; parallel wave)
    - fix (proponent/skeptic/arbiter): month index = year*12+month; pin fixture so the old rule rejects it; argue against B′ (same-month and month-skipping gaps) rather than a bucket-overlap strawman; correct the ceiling's rationale; state the n=3 trade-off with a test; mark the check group as a side effect; cite the posting-date constraint; report inflow changes (none); payment-status false "Unpaid" to a follow-up issue; generalize production-derived wording
- [reviewed — folded] whole-proposal (first wave): stale after the approach fixes rewrote Success criteria; its points (public-repo wording, criteria 1c/1d not exercising the rule, detected-vs-counted, insurance mechanism, unpaid headline) were merged into the draft (tier: reviewer; parallel wave)
- [reviewed — folded] whole-proposal (restart — approach fixes rewrote Success criteria): unit tests switched to fixed dates per knowledge 004's pure-function clause; route test freezes the clock; boundary twins at 14/15/45/46; deterministic irregular fixture; Goal bounded to ~two-week drift; generic wording; post-deploy report goes to the user only (tier: reviewer)
- [rechecked — residual folded] whole-proposal: all 6 items addressed; residual — Dec→Jan case moved to 37–45 days so only the calendar path admits it, and the monthly-only gate is stated and tested
