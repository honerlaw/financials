# Scratchpad: account-reconnect-flow

> **Ephemeral working memory.** Most of what lands here is noise — small
> decisions that don't matter, dead ends, momentary confusion. At feature
> completion, run `minerva:promote`: significant items get promoted to
> `.minerva/knowledge/`, `proposal.md` gets updated to match reality, and
> the raw scratchpad is archived.

## Balanced decisions 2026-06-30
- [reviewed — clean] scope check: single unit (Skeptic verdict revise, but all its concerns — enumerate the two endpoints, the new PlaidClient method, multi-institution banner, status-write test — were already resolved in the approach; its actual scope finding "single-unit boundary is defensible" = accept).
- [reviewed — folded] approach: Plaid update-mode reconnect + context-processor banner (Skeptic accept-with-concerns). Folded two load-bearing contract risks: (1) `create_update_link_token` omits `transactions` as well as `products`; (2) both new endpoints decorated `@login_required`. Incorporated low notes: keep authenticated fast-path in context processor, ignore onSuccess args explicitly, full-sweep sync acknowledged as consistent with /api/sync.
- [decided] whole-proposal soundness: sound (solo) — additive surface (1 context processor, 2 endpoints, 1 PlaidClient method, template edits), no public/cross-cutting contract, no knowledge conflict, low blast radius.
- [decided] baseline: pre-existing failure `tests/test_bills.py::test_inactive_sorts_last` on date 2026-06-30 (date-relative fragility, knowledge 004) — out of scope; completion criterion is "no NEW failures vs. baseline of 124 passed / 1 pre-existing fail".
- [reviewed — clean] completion verification: Verifier verdict `accept` — all 7 success criteria independently reproduced (134 passed, 1 pre-existing fail); no unmet criterion, no gaps.
- [decided] review triage (solo): minerva audit = spec-faithful, knowledge-compliant; inline code review = 0 FIX findings, 2 SUGGEST (Plaid SDK + helper load on all authed pages; context processor query per authed render) — both already-accepted tradeoffs → IGNORE. No replan-vs-FIX gate triggered.
- [decided] promote (solo): PROMOTE → new knowledge entry `007-decision-plaid-reconnect-update-mode.md` (bug fix + Plaid update-mode contract). No TODOs/followups. Proposal Approach already faithful to shipped reality; Status → Shipped (2026-06-30).

---

## Promoted 2026-06-30
Knowledge promoted to `.minerva/knowledge/007-decision-plaid-reconnect-update-mode.md`. Raw working notes above retained for history; proposal.md reflects shipped reality.
