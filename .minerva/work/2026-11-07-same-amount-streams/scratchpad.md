# Scratchpad: same-amount-streams-and-suggestions

**Started**: 2026-11-07
**Proposal**: proposal.md

## Decisions 2026-11-07
- Scope (two parts: exact-amount fallback split + "Possibly recurring" suggestions) — [reviewed — clean] Skeptic found the scope matched the user's chosen "Both".
- Approach A (exact-amount fallback split, monthly+active only; suggestions from leftovers) — [panel — 3/3 accept, 3 with fixes] panel because it amends knowledge 003 (amount must never gate detection); fixes folded: corrected the Why example (half-month plans are already biweekly), card-payment exclusion judged on the whole group, transfers kept with a badge.
- Whole-proposal soundness, first wave — [reviewed — revise] held until scope and approach were final; its points were folded with the panel's fixes.
- Whole-proposal soundness, restart — [reviewed — clean] Skeptic accepted; ten wording notes folded (Flag/Not recurring links both omitted beside a sub-stream, per-bin calendar-month caveat, biweekly in rejection list, refund wording, "no stream as a whole", "normally", input rows/tiebreak, late-second-plan undercount, /subscriptions wording, frozen-clock route tests).

- Completion verification — [reviewed — Verifier: INCOMPLETE → folded] code matched every Approach claim; two test gaps (criterion 2g: the flag-it-first note was never rendered in a test; 3b: Flag and Not recurring links were indistinguishable) closed with two route tests. 497 pass.

## Notes
- Local replay (uncategorized cache, not committed) reproduced the design replay: the expected same-amount monthly plans, and a suggestion list topped by P2P, vet, rental, counseling and pet payees. Card payments and transfers only drop out in production, where categories exist.
