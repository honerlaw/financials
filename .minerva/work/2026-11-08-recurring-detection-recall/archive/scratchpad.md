# Scratchpad: recurring-detection-recall

> **Ephemeral working memory.** Most of what lands here is noise — small
> decisions that don't matter, dead ends, momentary confusion. At feature
> completion, run `minerva:promote`: significant items get promoted to
> `.minerva/knowledge/`, `proposal.md` gets updated to match reality, and
> the raw scratchpad is archived.

## Decisions 2026-11-08
- [escalated to user] new-bill handling (pre-propose): count 2-charge pairs, badged 'new' vs list as possibly recurring — user chose count, badged
- [reviewed — clean] scope check: one unit, one PR (tier: reviewer — three changes across subscriptions.py/bills.py/template, not single-surface; parallel wave). Skeptic's pair-precision / code-path concerns were approach items, carried to the approach panel's fixes
- [panel — 3/3 accept, 3 with fixes] approach: A, three targeted relaxations; B (trailing window) and C (global dials) rejected on replay/knowledge 003 (tier: panel — knowledge tension with 003, 2026-10-26 and 2026-11-07 split; parallel wave)
    - fix (all): name the knowledge amendments to 003, 2026-10-26 and 2026-11-07 split
    - fix (skeptic/arbiter): break down the replay's pair count by whole-group vs in-group, with the false-positive impact in aggregate
    - fix (all): state the 23-day weekly window and the 52/12 overstatement as accepted risks
    - fix (skeptic/arbiter): widen the irregular negative test to 2–25 day gaps; test that a 14-day median stays biweekly; test that a non-Zelle TRANSFER_OUT is unchanged; per-row Zelle voting
    - fix (skeptic/arbiter): specify and test rule-claim, suggestion-dedupe and key-change interactions
    - fix (all): synthetic fixtures only; follow-up issue for Zelle grouping with no real data
- [reviewed — clean] whole-proposal (first wave): discarded at the restart check (tier: reviewer; parallel wave)
- [reviewed — folded] whole-proposal (restart): approach fold rewrote ## Success criteria, so the first-wave review went stale. Folded: weekly change's shared scope (income/rules/subscriptions) + weekly income criterion; pair→3-charge transition criterion; change-2 replay count; rollback path (tier: reviewer — knowledge-tension clause already approved by the approach panel, so it does not re-fire)
- [rechecked — residual folded] whole-proposal: item 2 (whole-group pair precision) partially addressed — stated as an accepted risk; also folded: `new` False after the third charge, and the 3-charge in-group edge case
- [reviewed — clean] completion verification: Verifier reproduced criteria 1–12 (558 passed) and accepted 13 as correctly deferred post-deploy (tier: reviewer floor — no interface change beyond the approved proposal); its one note (a stale test-file reference) was fixed
- [solo] review triage: 16 FIX / 0 SUGGEST / 1 IGNORE (tier: default-solo row — no item had two defensible dispositions). FIX: weekday guard on the skip allowance (code-review #1, #9), outflow-based whole-group pair naming (#2, #16), word-boundary case-insensitive Zelle match (#3), no pairs for card payments or transfers (#4), badge text and tooltip (#5, #6), rewrite unpushed branch history (#7), discriminating suggestion test plus missing-case tests (#10, #11, #12), stale comments and docstrings (#13–15), proposal reconciliation at promote (#17). IGNORE #8: the aggregate replay description is deliberate and has no merchants or amounts
- [solo] replan-vs-FIX on code-review #1: FIX, not replan. The weekday guard narrows change 1's skip allowance. Goal, approach and criteria are unchanged; criterion 1's fixture keeps its weekday (tier: no load-bearing divergence, so no panel convened)

## Work notes
- Skip-allowance precision (simulation, 3000 random series of 12 gaps uniform over 3–14 days): plain rule 2.3% pass as weekly; skips unguarded 28%; skips with plain ≥ 50% 23%; ±1 multiples 15%; weekday share ≥ 0.4 3.7% (6-gap series: 5% plain, 14% guarded). Thresholds 0.5 and 0.6 cut the target weekly stream's detection for months, because posting dates drift its weekday. Picked 0.4.
- Production replay after the guard: the same 2 new weekly streams and 8 new pairs, with no other stream changed.
- Harness gotcha: `harness.py` puts the primary checkout first on sys.path, so import the worktree's `app` before importing the harness or you replay main's code.

- [solo] promote partition: 1 PROMOTE (decision entry 2026-11-08-decision-detect-skipped-weeks-zelle-payments-and-new-pairs), 5 MERGE INTO PROPOSAL (weekday guard, Zelle word match, transfer-free pairs, outflow-based whole-group naming, badge text), 1 DISCARD (harness sys.path gotcha: session tooling, never committed), 1 TODO (tier: default-solo row — no entry had two defensible buckets)
- [solo] TODO disposition: Zelle payee grouping → GitHub issue #64, priority high (clears the deferral bar: writable failure scenario; urgent now that Zelle outflows count; too large to absorb because it needs a GROUPING_ALGO_VERSION bump and an index rebuild) (tier: default-solo row)
