# Proposal: subscriptions-view

**Date**: 2026-06-07
**Status**: Shipped (2026-06-07)

## Goal

Add a `/subscriptions` page that detects recurring transaction streams (weekly,
biweekly, monthly, quarterly, annual) via local fuzzy matching and shows each
stream with an active/inactive status.

## Why

Recurring charges are hard to spot scanning the monthly transaction list — one
view should answer "what's charging me on a schedule, how much is it typically,
and is it still happening?" without enabling a new Plaid product (Plaid's
Recurring Transactions API was considered and rejected: separate billed
product, black-box rules).

## Approach

- **New `app/subscriptions.py`** — pure function `detect_subscriptions(transactions, today)`
  returning a list of stream dicts. No DB schema changes; computed live on page
  load (fine at personal-finance data volumes).
- **Grouping:** key by `merchant_entity_id` when present, else a normalized
  merchant key — lowercased `merchant_name` (falling back to `description`),
  digits/punctuation stripped, noise tokens (`com`, `inc`, …) dropped — so
  "NETFLIX.COM 866-..." and "Netflix" normalize identically. Remaining
  near-identical keys fuzzy-collapse via `SequenceMatcher` ratio ≥0.82 plus a
  ≥5-char prefix guard (the prefix guard exists because ratio alone missed
  prefix-shaped variants like "SPOTIFY USA" vs "Spotify"). Grouping is
  global across accounts/institutions; contributing accounts are shown per
  stream so a card switch doesn't split a stream.
- **Cadence detection (the only gate):** for groups with ≥3 charges (≥2 for
  annual), compute inter-charge gaps (same-day charges count as one
  occurrence); the median gap maps to the nearest bucket — weekly 7±2,
  biweekly 14±3, monthly 30±6, quarterly 91±12, annual 365±30 — and
  additionally ≥70% of individual gaps must sit inside the bucket tolerance,
  rejecting irregular merchants (e.g. frequent grocery runs) whose median
  accidentally lands in a bucket. See
  `.minerva/knowledge/003-decision-subscriptions-cadence-only-detection.md`.
- **Everything recurring:** no category exclusions — card payments, transfers,
  utilities, and recurring inflows (paychecks) all qualify. Inflows are
  visually distinguished. Pending transactions count (they're real charges;
  excluding them would falsely mark fresh streams inactive). `removed=True`
  rows are excluded.
- **Amount display:** median amount shown; "varies" badge when the median
  absolute deviation exceeds 25% of the median (MAD, so a single price hike
  doesn't flag "varies" but genuine swings do). Amount never gates
  detection — card payments and utilities vary wildly and must still be
  detected.
- **Status:** `inactive` when `today − last_charge > 1.5 × cadence_days`,
  else `active`. Next-expected date = last charge + cadence.
- **Route/UI:** `/subscriptions` page + navbar link (mirroring the
  Transactions link pattern), table sorted active-first: merchant, cadence,
  typical amount (+varies badge), last charge, next expected, occurrence
  count, accounts, status pill.
- **Tests:** unit tests for normalization/fuzzy-collapse, each cadence bucket,
  variance rejection, active/inactive boundary (1.5×), inflow handling, the
  annual 2-occurrence rule; route test for auth + rendering.

## Success criteria

- `/subscriptions` lists detected streams; merchant-name variants and amount
  jitter don't split a stream
- Each row shows cadence, median amount (with varies badge when amount MAD
  >25% of median), last charge, next expected, accounts, occurrence count,
  and an active/inactive status pill
- A stream overdue by >1.5× its cadence renders inactive; one within that
  window renders active
- Recurring inflows appear, visually distinct from outflows
- All existing + new tests pass

## Open Questions

- Fuzzy-collapse similarity threshold and gap-variance bound may need tuning
  against real synced data once live (constants: 0.82 similarity, ≥5-char
  prefix guard, 70% gap regularity, 0.25 MAD ratio — all provisional)
- No bimonthly (~60-day) bucket: cadence buckets are disjoint (monthly caps
  at 36d, quarterly starts at 79d), so true every-two-months charges are
  silently not detected
