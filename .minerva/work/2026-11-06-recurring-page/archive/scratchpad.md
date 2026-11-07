# Scratchpad: recurring-page

> **Ephemeral working memory.** Most of what lands here is noise — small
> decisions that don't matter, dead ends, momentary confusion. At feature
> completion, run `minerva:promote`: significant items get promoted to
> `.minerva/knowledge/`, `proposal.md` gets updated to match reality, and
> the raw scratchpad is archived.

## Decisions 2026-11-06
- [escalated to user] intake design (pre-auto, minerva:propose): user chose new /recurring page over extending /bills; income vs expenses; split counted/not-counted; collapsed not-counted grouped by reason; income P25; pay cadence confirmed
- [user-directed] approach: new /recurring page (user picked it over extending /bills in place during propose intake)
- [reviewed — clean] scope check: single unit, one PR (tier: reviewer — multi-file, removes two routes so not additive; Skeptic accept, noted income-classification, single-pass and test-migration concerns, carried to whole-proposal; parallel wave)
- [reviewed — folded] whole-proposal: folded test migration incl. query-count guard, INCOME-category gate for income (uncategorized not counted), single-pass detect_recurring_from_groups, income total sums rounded rows, left-over iff counted income ≥1, 302 not 301, status summary kept, no badge on not-counted rows, estimator labels (tier: reviewer — not provably small; parallel wave)
- [rechecked — residual folded] whole-proposal: item 4 partially addressed (26/12 not pinned through the route) — added route test with biweekly INCOME_WAGES stream; also added unauthenticated-redirect test

## Work notes
- Criterion wording fix (routine, not a divergence): "26 biweekly deposits, not 27" was arithmetically wrong — deposits at 0,14,…,364 days back are 27 dates inside an exclusive 365-day window. The rule (exclusive far end, same as expenses) is unchanged; the criterion now pins "a deposit 365 days before the latest is ignored". The count never affects a fixed paycheck's P25 anyway.
- Historical mentions of /bills and /subscriptions (measured costs, the 20 s bug) left in merchant_groups.py docstrings — they describe the past, not current routes.

## Decisions 2026-11-06 (work / review)
- [reviewed — clean] completion verification: Verifier reproduced criteria 1–3, criterion 4 confirmed by full run (371) + targeted rerun after docstring edits (205), criterion 5 legitimately post-deploy (tier: reviewer floor — no interface change beyond what the proposal approved)
- [solo] review triage: 7 FIX / 1 SUGGEST / 2 IGNORE (tier: default-solo row — no finding had two defensible dispositions; #3 card-autopay status: the proposal approved no badge on uncounted rows after review, and the dashboard account cards already flag overdue card payments from Plaid liabilities, so IGNORE dominates)

- [solo] promote partition: 1 PROMOTE (decision entry 2026-11-06-decision-recurring-page-and-income-rule, absorbing review finding #10 and triage #3 rationale) / 1 MERGE (criterion wording, Approach additions) / rest DISCARD / 0 TODO (tier: default-solo row — no entry had two defensible buckets)

## Review triage 2026-11-06
Code review (local-diff mode, fresh-context subagent) + inline minerva audit (no audit findings).
1. [low] summary flex space-between pushed label away from arrow — FIX (removed justify-content)
2. [low] _EXCLUDED_GROUPS hard-codes reasons; a new reason would vanish — FIX (unknown reasons get their own group; test_every_bill_exclusion_reason_has_a_group)
3. [low] active card-autopay rows lost their Unpaid badge — IGNORE (approved design; dashboard flags overdue card payments)
4. [medium] window test passed with the boundary moved — FIX (test_income_window_excludes_its_far_end, 3 deposits so the edge changes P25)
5. [low] negative left-over untested — FIX (test_left_over_renders_negative_when_expenses_exceed_income)
6. [low] sort orders untested — FIX for counted largest-first (test_counted_expenses_are_largest_first); income ordering IGNORE
7. [low] focus ring clipped by card overflow — FIX (inset outline-offset)
8. [low] CSS arrow read aloud — FIX (content alt text "")
9. [low] detect_*_from_groups only test callers; monthly_income_total alias — IGNORE (intentional per proposal)
10. [low] knowledge 2026-10-26 entries name /bills and test_bills_page_* — SUGGEST → promote

## Review finding 2026-11-06
- Knowledge entries 2026-10-26-decision-fixed-monthly-bills-total ("/bills leads with…") and 2026-10-26-bug-commit-before-detection-reloaded-every-transaction (names test_bills_page_*) describe the page as /bills; the page is now /recurring and those tests are test_recurring_page_*.
