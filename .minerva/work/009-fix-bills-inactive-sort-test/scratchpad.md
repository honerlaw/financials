# Scratchpad: fix-bills-inactive-sort-test

> **Ephemeral working memory.** Most of what lands here is noise — small
> decisions that don't matter, dead ends, momentary confusion. At feature
> completion, run `minerva:promote`: significant items get promoted to
> `.minerva/knowledge/`, `proposal.md` gets updated to match reality, and
> the raw scratchpad is archived.

## Quick decisions 2026-06-30
- [decided] scope check: single tiny unit — one test-only fix in tests/test_bills.py.
- [decided] approach: use fixed TODAY constant for both seed + `today` arg (dominant — pure function + fixed today + fixed seeds is fully deterministic per knowledge 004; the unpaid/paid/upcoming classification is calendar-day sensitive so reseeding relative to date.today() risks paid/upcoming edge cases). Also added 'unpaid'/'inactive' membership asserts for a clear failure message.
- [decided] whole-proposal soundness: test-only change, no public interface, aligns with knowledge 004 — sound. Escalation predicate: no clause holds → decide directly.
- [decided] completion verification: all 3 criteria met — targeted test passes, no date.today() call in the fixed test (only a comment mention), full suite 135 passed / 0 failures. No divergence.
- [decided] review triage: minerva audit spec-faithful + knowledge-compliant; code review 0 findings (the other two date.today() tests are consistently-relative, time-invariant — left untouched).
- [decided] promote partition: no new knowledge (fix is a direct application of existing knowledge 004 — a new entry would duplicate it); decisions are routine noise → DISCARD; proposal Approach already faithful. No TODOs.
- [synthesis] no-op (below threshold: only entry 007 unsynthesized from prior run, no new scope this run, no link rot).

---

## Promoted 2026-06-30
No knowledge promoted (instance of existing pattern [[004-pattern-seed-relative-dates-in-time-sensitive-tests]]). proposal.md reflects shipped reality; raw notes retained for history.
