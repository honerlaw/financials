# Subscription detection gates on cadence regularity only — amount similarity must never gate

**Date**: 2026-06-07
**Type**: decision
**Summary**: Recurring-stream detection gates on cadence regularity alone — amount similarity must never gate, or card payments and utilities disappear from `/subscriptions`.
**Context**: .minerva/work/004-subscriptions-view (see git history if the worktree has been cleaned up)

## Context

Work unit 004 added the `/subscriptions` page: a pure-function detector
(`app/subscriptions.py`) that groups transactions by fuzzy-matched merchant
and classifies recurring streams into weekly / biweekly / monthly / quarterly
/ annual cadences, with active/inactive status. The scope decision was
"everything recurring" — card payments, transfers, utilities, and inflows
(paychecks) all qualify, with no category exclusions.

The obvious design is to require both a regular charge cadence *and* a
consistent amount ("a subscription is a fixed recurring price"). That design
is wrong for this scope.

## Finding

Three interlocking decisions, validated by `tests/test_subscriptions.py`:

1. **Cadence regularity is the only detection gate.** Amount similarity must
   never gate detection: card payments ($500 one month, $3,000 the next) and
   utilities vary wildly yet are exactly the recurring streams the page
   exists to show. Amount dispersion only drives a display badge.

2. **Median-gap bucket fit alone is insufficient.** A frequent-but-irregular
   merchant (grocery runs every 2–10 days) can have a *median* gap that
   accidentally lands inside a cadence bucket. Detection additionally
   requires most gaps to be individually regular (currently ≥70% of gaps
   within the bucket's tolerance) — without this, irregular merchants sneak
   in as fake weekly streams.

3. **The "varies" badge uses MAD, not max-deviation.** Median absolute
   deviation relative to the median (currently MAD/|median| > 0.25) means a
   single price hike across an otherwise fixed-price history does NOT flag
   "varies" (MAD stays 0), while genuinely variable bills do. Max-deviation
   would false-flag every price change.

## Implications

- Re-adding an amount-similarity gate later would silently drop card
  payments and utilities from detection — a regression, not a cleanup.
- The numeric constants (70% gap regularity, 0.25 MAD ratio, 0.82 fuzzy
  similarity, ≥5-char prefix guard) are **provisional** — they were chosen
  against synthetic test histories and have not yet been tuned against real
  synced data. The proposal's Open Questions and
  `.minerva/work/004-subscriptions-view/followups.md` track this. The
  *shape* of the rules above is the durable part; the dials are not.
- There is deliberately no bimonthly (~60-day) bucket: buckets are disjoint
  (monthly caps at 36d, quarterly starts at 79d), so true every-two-months
  charges are silently not detected. Recorded as an Open Question.

## Related

- [[004-pattern-seed-relative-dates-in-time-sensitive-tests]] — see also
  why the detector takes its reference date as a parameter instead of calling `date.today()`.
- [[006-decision-bills-payment-status-algorithm]] — see also
- [[008-decision-dashboard-spend-and-weekly-budget]] — see also
