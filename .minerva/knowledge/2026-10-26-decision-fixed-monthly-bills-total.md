# /bills leads with a fixed monthly total: P75 of the last year × cadence factor, sub-annual streams only

**Date**: 2026-10-26
**Type**: decision
**Theme**: recurring-detection
**Summary**: Fixed monthly total sums P75-of-last-year × cadence factor over active, sub-annual, non-transfer bills.
**Context**: .minerva/work/2026-10-26-bills-monthly-total (see git history if the worktree has been cleaned up)

## Context

The user asked for their total fixed monthly expenditure, with variable bills
"averaged" in a way that "weights a bit on the higher end". `/bills` listed recurring
outflows with a per-bill median but no total and mixed cadences. Production data
showed the annual bucket (`MIN_OCCURRENCES_ANNUAL = 2`) sweeps in one-offs: a large
tax payment and seasonal or one-off retail purchases a year apart.

## Finding

`app/bills.py` adds `monthly_amount` and `excluded_reason` to every bill and
`fixed_monthly_total(bills) -> (total, count)`:

1. **Estimate** = 75th percentile (linear interpolation) of per-occurrence amounts ×
   `MONTHLY_FACTOR` (weekly 52/12, biweekly 26/12, monthly 1, quarterly 1/3, annual
   1/12), rounded to cents. An occurrence is one date, its amount the sum of that date's
   **positive** charges (refunds ignored) — the same unit `_build_stream` counts cadence
   in. Only occurrences in the 365 days ending at the stream's last charge count,
   exclusive of the far end (12 monthly occurrences, not 13). P75 equals the price for a
   fixed bill, leans high for a variable one, and one spike cannot set it.
2. **Counted** = active, cadence weekly/biweekly/monthly/quarterly, not a transfer.
   `excluded_reason` is the first of `inactive`, `annual`, `transfer`; every bill stays
   listed (knowledge 003) with its monthly equivalent and the reason it is not counted.
3. **Transfer** = a strict majority of the stream's *categorized* rows have a `TRANSFER*`
   primary `category` or `category_detailed == LOAN_PAYMENTS_CREDIT_CARD_PAYMENT`.
   Uncategorized rows abstain (the category columns arrived in a later migration, so an
   old autopay stream is mostly uncategorized history); a wholly uncategorized stream is
   not a transfer. **Deliberately unlike `spending.is_spend` (knowledge 008)**, other
   `LOAN_PAYMENTS` — mortgage, car, student loan — are fixed bills and count.
4. The total sums the rounded per-bill figures, so it equals the sum of displayed rows.

## Implications

- Genuine annual fees (memberships, card fees) are under-counted by design until the
  annual bucket is trustworthy; interest charges are counted; probably-late streams the
  `active` rule calls inactive are not. There is no per-bill override — it would need a
  bill identity that survives merchant-index rebuilds (029/031).
- Rent paid by Zelle tagged `TRANSFER_OUT` would be excluded; a weekly false positive
  carries a 52/12 factor. The per-row reason keeps each such case inspectable.
- P75 over a 12-month window lags a price increase by ~3–4 months.

## Related
- [[003-decision-subscriptions-cadence-only-detection]] — detection and list membership unchanged; the total only flags
- [[005-decision-bills-inactive-override]] — `inactive` is checked first, mirroring its active guard
- [[008-decision-dashboard-spend-and-weekly-budget]] — shares the card-payment double-count rationale; diverges on non-card `LOAN_PAYMENTS`
- [[2026-10-26-bug-commit-before-detection-reloaded-every-transaction]] — shipped in the same unit
