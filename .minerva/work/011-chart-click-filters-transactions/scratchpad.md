# Scratchpad: chart-click-filters-transactions

> **Ephemeral working memory.** Most of what lands here is noise. `minerva:promote`
> sifts the durable few into `.minerva/knowledge/`; the rest is archived.

## Quick decisions 2026-07-05

- [decided] scope check: single additive unit — one route + one template + api endpoint + tests; builds on 010's spending section. No decomposition.
- [decided] approach: URL-param date window (`?start`/`?end`) + server filter, mirroring the existing `?institution`/`?month` pattern; window takes precedence over month for the table; chart stays on the month. Rejected: client-side row filtering (infinite scroll only loads 50 rows, so it can't filter the full set). Escalation predicate clear on all clauses (dominant approach, additive/bounded/reversible, no public-interface/contract change, no knowledge conflict) → decided directly. Counter: 0.
- [decided] whole-proposal soundness (solo): sound — reuses `_month_bounds`/query pattern, honors [[004]] (chart pure fns untouched), no new cross-cutting contract.
