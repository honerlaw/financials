# Scratchpad: chart-click-filters-transactions

> **Ephemeral working memory.** Most of what lands here is noise. `minerva:promote`
> sifts the durable few into `.minerva/knowledge/`; the rest is archived.

## Quick decisions 2026-07-05

- [decided] scope check: single additive unit — one route + one template + api endpoint + tests; builds on 010's spending section. No decomposition.
- [decided] approach: URL-param date window (`?start`/`?end`) + server filter, mirroring the existing `?institution`/`?month` pattern; window takes precedence over month for the table; chart stays on the month. Rejected: client-side row filtering (infinite scroll only loads 50 rows, so it can't filter the full set). Escalation predicate clear on all clauses (dominant approach, additive/bounded/reversible, no public-interface/contract change, no knowledge conflict) → decided directly. Counter: 0.
- [decided] whole-proposal soundness (solo): sound — reuses `_month_bounds`/query pattern, honors [[004]] (chart pure fns untouched), no new cross-cutting contract.
- [decided] work: no divergence — built approved approach (`_table_date_bounds` + selectWindow/clearWindow JS + window indicator). Clicking a spend bar filters to ALL transactions that day (not just spend-classified) — the literal, least-surprising reading of the seed.
- [decided] completion verification (solo self-check): all 7 criteria met — window filtering on `/` + `/api/transactions`, precedence over month, malformed-input fallback (no 500), indicator/clear, chart stays month-scoped. 162 tests green + manual render confirmed week/day filtering.
- [decided] review triage (solo): minerva audit clean; code review found no correctness bugs. 1 LOW SUGGEST below. No replan-vs-FIX.

## Review finding 2026-07-05
- [SUGGEST] Clickable chart divs (week cards, day bars) use onclick without `role="button"`/`tabindex`, so they aren't keyboard-focusable. Low priority for this personal app; revisit if accessibility becomes a goal.

- [synthesis] no-op (only 009 un-synthesized; a minor extension of the already-synthesized [[008]] spending-views theme — below refresh threshold, no link rot)
