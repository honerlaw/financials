# Scratchpad: descriptor-merge

> **Ephemeral working memory.** Most of what lands here is noise — small
> decisions that don't matter, dead ends, momentary confusion. At feature
> completion, run `minerva:promote`: significant items get promoted to
> `.minerva/knowledge/`, `proposal.md` gets updated to match reality, and
> the raw scratchpad is archived.

## Decisions 2026-11-06
- [user-directed] direction: option 1 "also match on the raw card descriptor", keeping the 032 entity rule (user answered "1")
- [solo] scope check: single unit, one PR (tier: solo predicate — one pure function in subscriptions.py plus two call sites, additive merge step, no schema/index/interface change, no knowledge conflict; evidence: prod simulation counts; parallel wave)
- [reviewed — folded] approach: C (post-grouping merge at detection time) over A (descriptor signal inside both grouping paths + algo-version rebuild) and B (descriptor-first grouping_key); folded total order, ambiguous-bucket rule (2+ entity ids → no merge), date-disjointness, 5-char minimum (tier: reviewer — new behaviour, not provably small; 029 tension doubt resolved: 029 constrains quadratic work and requires reading the index, C is linear and reads it; parallel wave)
- [rechecked — residual folded] approach: all items addressed; residual — criterion 4 now distinguishes an entity-id block from an overlap block
- [reviewed — folded] whole-proposal: folded side split, non-mutation, memoized normalize, single merge per request, renamed corpus in parity tests, permutation test, entity-shape disclosure and satisfiable criterion 4, wording ("Plaid name" not "raw descriptor"; rows vs distinct dates distinguished), no real names committed (tier: reviewer; parallel wave)
- [rechecked — residual folded] whole-proposal: items 3/4/8 partial, non-load-bearing — added original_description rationale, no-op note, strict-overlap rationale, three-group chain test

## Work notes
- Re-simulation with the revised rules on prod data (name keys only): a few merges; the reported bill becomes active monthly; a couple of one-off purchases become annual (listed, not counted). A second renamed stream found by the first simulation no longer merges (its two names overlap in time) — left split, as today.
- Test fixtures (FakeTxn in test_subscriptions.py / test_bills.py) defaulted every description to 'CHARGE', so the merge fused unrelated sequential fixture merchants (test_streams_sorted_active_first failed). Fixtures now default description to merchant_name — real rows always carry a merchant-specific descriptor. Any future fixture that shares a placeholder descriptor across merchants will merge them.
- Perf: merge_by_descriptor on a production-sized corpus (about a thousand groups, several thousand rows) takes under 10 ms. The reported bill comes out as one active monthly stream.

## Review triage 2026-11-06
- Verifier (completion): 3/4 criteria met pre-deploy; criterion 1 gap — `test_without_merge_the_renamed_bill_splits` was vacuous → FIX (now asserts the real split via `_group_transactions` + detection without the merge).
- Code review: greedy `accumulated[-1]` check let two short groups nested inside a concurrent long group merge → FIX (any overlapping pair on a side blocks the whole side).
- Code review: `_group_order` tie-break incomplete (equal dates/name/size/descriptions could fall to input order) → FIX (amounts and entity ids added to the key).
- Code review: production figures (counts, cadence) in this unit's and unit 1's records — public repo → FIX (redacted; unit 1's history on main still holds them — reported to the user).
- Added tests: concurrent group blocks its side; same-day boundary counts as overlap; renamed deposits merge.

## Decisions 2026-11-07
- [solo] triage: all four findings FIX, none load-bearing for the design (tier: solo — triage, reviewer ceiling; each fix tightens a stated rule without changing it)
- [solo] promote partition: one knowledge entry (decision, theme recurring-detection); fixture-default note folded into it; no TODOs to dispose (tier: solo)
- [solo] squash branch history before push so pre-redaction commits never reach GitHub (operational)
