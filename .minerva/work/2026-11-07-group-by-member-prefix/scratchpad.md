# Scratchpad: group-by-member-prefix

**Started**: 2026-11-07
**Proposal**: proposal.md

## Decisions 2026-11-07
- [reviewed — clean] scope check: one unit, one PR, no phases (tier: reviewer — two grouping modules, not a single surface; parallel wave). Skeptic accepted; its design notes (hub guard, v1→v2 test, false "unchanged" claim, stale docs) were carried into the approach fold.
- [reviewed — folded] approach: A (member-key word-prefix join in both paths) over B (request-time descriptor-prefix merge), C (facilitator-prefix stripping), D (rules only); folded live-keys-only indexed members, the 031-style regroup test, the corrected invariant, the name-only replay disclosure, alternative E, the hub guard, and dropped representatives as members (tier: reviewer — interface-clause doubt passed to the Skeptic, which answered "no": grouping is internal and the index is a versioned derived cache; parallel wave)
- [rechecked — residual folded] approach: fold-audit found all 9 items addressed; residuals folded (fixtures that cannot pass vacuously, every same-pass key becomes a member, parity compared without row ids)
- [reviewed — clean] whole-proposal (first wave): discarded as stale — the approach fold rewrote Success criteria (restart check)
- [reviewed — folded] whole-proposal (restart): folded the same-pass member wording, minimum-length fixture, merge_by_descriptor double-count consequence, parity comparison, rebuild cost, replay evidence for the reported case, fictional fixture text, the _group_transactions docs; the entity criterion made non-vacuous (tier: reviewer)
- [rechecked — residual folded] whole-proposal: fold-audit accepted (9 addressed, rebuild cost partial — not load-bearing, bounded under the 120 s timeout); folded the cost wording, the incremental entity-key test, the ranged-candidate preview, the entity-group example

- [reviewed — Verifier: revise → test gap closed] completion verification: criteria 1–4 met (13 mutants run; all but one killed); the surviving mutant (dropping the live filter on already-indexed member keys) exposed an untested Approach claim, not an unmet criterion — closed with an incremental removed-member test; 534 pass (tier: reviewer floor — no interface change beyond what the proposal approved)

## Notes
