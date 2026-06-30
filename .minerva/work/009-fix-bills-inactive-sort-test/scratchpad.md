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
