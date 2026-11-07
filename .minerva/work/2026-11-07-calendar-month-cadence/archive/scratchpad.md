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
- [reviewed — clean] completion verification: Verifier reproduced criteria 1–3 (mutation-tested every rule variant; route test fails on main's detector), 4 correctly deferred to post-deploy (tier: reviewer floor)
- [solo] review triage: 1 FIX (stale GAP_REGULARITY comment — doc for touched behaviour) / 0 SUGGEST / 0 IGNORE; code review had no findings (tier: default-solo row — no item had two defensible dispositions)
- [solo] promote partition: PROMOTE decision (refines 003) + pattern (freezegun login); MERGE approach details into proposal; TODO payment status; DISCARD the rest (tier: default-solo row)
- [solo] TODO disposition: false "Unpaid" → issue #58, priority high — defect with a writable scenario, too large to absorb (changes 006 for every bill) (tier: default-solo row)

## Work notes
- Route test with `@freeze_time` failed with a /login redirect: `auth_client` logged in at real time, and Flask's timestamped session cookie reads as from the future under the frozen clock. Logged in inside the frozen body → promoted as a pattern.
- Verified the route test fails against main's `app/subscriptions.py`.

## Review triage 2026-11-07
- Code review (independent): no findings; noted the `GAP_REGULARITY` comment is imprecise for the monthly bucket → FIX (applied).
- Minerva audit: diff matches Approach; fixed-date tests per 004; 006 unchanged; 003 shape kept.
