# Scratchpad: dashboard-spend-and-budget

> **Ephemeral working memory.** Most of what lands here is noise — small
> decisions, dead ends, reminders. `minerva:promote` sifts the durable few
> into `.minerva/knowledge/`; the rest is archived.

## Balanced decisions 2026-07-05

- [reviewed — folded] scope check: single unit (Skeptic accepted single-unit — argued against splitting chart vs. budget since they share one route/template/query; folded proposal clarifications on week-boundary padding + chart-vs-table default-month labeling).
- [reviewed — folded] approach: Approach A — server-side pure functions + dependency-free rendering (Skeptic confirmed A strictly dominant over B/coarse-weekly-bars and C/Chart.js-CDN; folded 4 gaps: (1) full Sun–Sat week padding of the query, (2) spending section gets its own explicit month header since it defaults to current month while the table stays all-time, (3) running-total highlight only for the week containing today and only when in range, (4) null-category outflow counted as spend, documented as provisional). Rejected: B (coarse ~4-5 bars, loses daily granularity), C (adds Chart.js client dep, moves logic off tested path).
- [decided] whole-proposal soundness (solo): sound — additive to one route/template, no new public interface/cross-cutting contract, aligns with [[004-pattern-seed-relative-dates-in-time-sensitive-tests]]. Escalation counter: 0.
- [decided] work: no load-bearing divergence — implemented the approved Approach A exactly (spending.py pure fns + _spending_context helper + template section). Added 2 tests (explicit-month render, institution-filter scoping) to close criteria 4 & 7 before the completion gate.
- [reviewed — clean] completion verification (Verifier): accept — all 7 success criteria independently reproduced, 155/155 tests pass, no gaps/overclaims.
- [decided] review triage (solo): minerva audit clean (spec fidelity + [[004]] compliance). Code review found 1 HIGH → FIXed: malformed `?month=` (truthy but unparseable) crashed `_spending_context` via `week_start(None)` → now falls back to current month, matching the table's tolerance; regression test added (156 passing). No load-bearing divergence → no replan-vs-FIX gate.

## Review finding 2026-07-05
- [SUGGEST] `spending.week_start` duplicates the inline Sun-start math in `routes._group_by_week` (`(weekday()+1)%7`). Not worth a cross-module refactor now; if a third caller appears, consolidate into one shared helper.
