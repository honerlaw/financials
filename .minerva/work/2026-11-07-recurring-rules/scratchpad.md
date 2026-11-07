# Scratchpad: recurring-rules

> **Ephemeral working memory.** Most of what lands here is noise — small
> decisions that don't matter, dead ends, momentary confusion. At feature
> completion, run `minerva:promote`: significant items get promoted to
> `.minerva/knowledge/`, `proposal.md` gets updated to match reality, and
> the raw scratchpad is archived.

## Decisions 2026-11-07
- [solo] scope check: one unit, one PR (tier: solo predicate — one feature on one page; additive table; parallel wave)
- [reviewed — revise, folded] approach: A (description rules applied per request) over B (merchant-key flags), C (MerchantGroup.id), D (merchant-key-scoped rules); Skeptic accepted A with concerns (stream visibility, direction, forced-cadence income, hint limits, SameSite wording, precedence) folded (tier: reviewer — new table + forms, override of 003)
- [rechecked — escalated] approach → panel: fold-audit found two new load-bearing concerns (real obligations listed in a public-bound criterion; sign split turning a bill rule's inflows into counted income)
- [panel — 3/3 accept, 3 with fixes] approach: A (tier: panel — upward move from fold-audit; quorum 3/3)
    - fix: required `direction` column; rules claim only rows of their sign; ≤1 stream per rule; inflow recurring counts only with a detected cadence, never forced
    - fix: criterion 6 says "the classifications the user gave in this conversation"; Why describes failure modes generically
    - fix: forced-monthly estimate = max(per-date P75 ×1, P75 of nonzero calendar-month totals in the window), with a test
    - fix: preview runs saved rules + candidate, shows N of M and rows taken/lost; route test
    - fix: `_build_stream(..., fallback_cadence=None)` used only when no cadence is found; annual stays annual
    - fix: Flag bullet states the transfer case needs the masked digits appended
    - fix: test that claiming changes leftover merging in merge_by_descriptor
    - fix: production writes are user-directed, each saved after its preview, deleted if wrong
- [reviewed — folded] whole-proposal (restart — dispatched before the approach was final; its points held and merged after the panel): range is a user amount gate + last-matched date; half-open ranges rank as ranged; id tie-break; identity partition with duplicate-row test; merge test in detection criteria; preview commit order; "Marked not recurring" row shape/branch/sort; stop-and-report covers transfer patterns (tier: reviewer)
- [rechecked — residual folded] whole-proposal (fold-audit of merged v3): all panel and held fixes addressed; residuals folded — rules loaded as plain rows (commit expiry) and a 1-vs-10-rule query-count check; candidate ranks after saved rules; Not-counted section renders for the new group alone; criteria for last-matched, 0 rows, badge, Add-a-rule default, transfer hint, taken-from rows; generic Why wording; zero-amount rows; "source groups" naming. Auditor: nothing touches the choice of A, so no further move up (tier: reviewer)

## Work notes
