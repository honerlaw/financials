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
- [reviewed — issues absorbed] completion verification: Verifier met 1, 3, 4, 5, and 2 with partial notes; 6 deferred to post-deploy. It mutation-tested direction, precedence, identity, override, by_month, inflow-never-forced, preview, query count and SameSite. Gaps closed: max floor test, value-equal twins kept, dominant-descriptor merge test, taken route test, headline assertion, required direction/action on POST; fixture label made generic (tier: reviewer floor)
- [solo] review triage: FIX NUL→Postgres 500 (strip control chars), Preview blocked by required Name (formnovalidate), min 0 ranks as a range (normalize to None), preview keyed by label (key by id), forced-stream false Unpaid (paid-this-month/upcoming), form copy on ungrouped rows. Biweekly-by-date false Unpaid on rule streams → Known consequences, the same class as issue #58, no new issue (low; existing 006 behaviour) (tier: default-solo row)
- [solo] promote partition: PROMOTE decision (user rules); MERGE as-built notes and Known consequences into proposal; DISCARD the rest (tier: default-solo row)
- [solo] TODO disposition: none open — the biweekly false Unpaid is folded into issue #58's class, recorded in Known consequences and the knowledge entry (tier: default-solo row)

## Work notes
- `flask db` needs FLASK_APP=wsgi.py for the knowledge-017 isolated migration check.
- The check-group route fixture writes the other checks on the payee's day so the mixed group still detects as monthly. Otherwise no Flag link renders.
