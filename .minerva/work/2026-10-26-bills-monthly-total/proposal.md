# Proposal: bills-monthly-total

**Date**: 2026-10-26
**Status**: Shipped (2026-10-26)

## Goal

1. **Total fixed monthly bills.** Show, at the top of the existing `/bills` page,
   the total fixed monthly expenditure: one figure, "Fixed bills: $X / month",
   equal to the sum of a per-bill monthly-equivalent estimate over the bills that
   represent an ongoing fixed obligation. Each bill row gains a **Per month**
   column showing its monthly-equivalent estimate; rows not counted in the total
   are visibly marked with why ("inactive", "annual", "transfer").
   - **Counted** = an active (`stream['active']`), outflow (already true of every
     bill) stream whose cadence is weekly, biweekly, monthly or quarterly, and
     which is not a credit-card payment or transfer.
   - **Monthly-equivalent estimate** = a "typical, leaning high" charge × a
     cadence factor (weekly 52/12, biweekly 26/12, monthly 1, quarterly 1/3,
     annual 1/12), rounded to cents.
   - **Typical, leaning high** = the 75th percentile (linear interpolation) of the
     stream's per-occurrence amounts within the 365 days ending at its last
     charge. For a fixed-price bill this equals the price; for a variable bill
     (utilities, interest) it sits above the median, as the user asked, without
     letting one outlier month set the figure the way a max would.
2. **Make `/bills` (and `/subscriptions`, which shares the defect) fast.** The
   user asked that the page be "somewhat performant". Production `/bills` takes
   **~20 s** today (measured 2026-10-26: 22.8 s, 20.0 s, 20.0 s; `/subscriptions`
   19.5 s; `/` 0.25 s). Target: the request issues a small constant number of
   queries regardless of transaction count, and production loads in a few seconds
   at most.

## Why

The user wants to know their total bills — "the total fixed expenditure every
month" — with variable bills (e.g. utilities) averaged in a way that "weights a
bit on the higher end". `/bills` already detects recurring outflows
(`app/bills.py`, reusing `subscriptions.py` cadence detection) but shows only a
per-bill median "Typical amount", no total, and mixes cadences, so the number
cannot be read off the page today. Mid-intake the user added: "make sure its
somewhat performant, I dont want to spend 25 minutes waiting for the page to load".

**Production data shaped the counting rules.** Production's `/bills` (read on
2026-10-26) showed that the **annual** bucket is noisy: `MIN_OCCURRENCES_ANNUAL = 2`
means any two similar purchases about a year apart read as an annual "bill" — a
large tax payment and several seasonal or one-off retail purchases among them.
Counting annual streams would have more than doubled the total with noise. Genuine
annual fees are under-counted by excluding them; they stay visible per row with
their monthly equivalent.

**Root cause of the 20 s, found by profiling.** A local Postgres seeded with a
production-sized synthetic dataset (7,500 transactions, about production's
volume, and ~2,100 merchant keys) reproduces it:
`routes.bills()` / `routes.subscriptions()` call `db.session.commit()` right after
`groups_for_detection()` has loaded every transaction as an ORM row and **before**
detection reads them. The commit expires every loaded instance
(`expire_on_commit`), so `_build_stream`'s first attribute access on each row
lazily re-SELECTs it: **7,505 queries per page load**. At ~2–3 ms per round trip
to the managed Postgres that is the ~20 s observed. Moving the commit to after
detection makes it **5 queries, 3.04 s → 0.19 s** locally on the same data, with
identical output (107 bills). Production syncs are clean (`/settings` SyncLog all
OK) and `is_index_usable()` is true on the reproduction, so the merchant-group
index works as designed (knowledge 029); the commit placement defeats it.

## Approach

*(Rewritten at promote to describe what shipped.)*

**A. Performance fix — two changes, in their own commits ahead of the feature.**

1. In `routes.bills()` and `routes.subscriptions()`, `db.session.commit()` moved to
   **after** `detect_*_from_groups(...)`. The commit still persists any index build
   `groups_for_detection()` just did; before detection it expired every loaded ORM row
   and detection re-SELECTed each one (7,505 queries).
2. `merchant_groups._detection_rows()` serves both `grouped_transactions()` and the
   in-memory fallback with a Core `select()` of the 11 columns detection reads
   (`_DETECTION_COLUMNS`), returning plain rows, not ORM instances. This was proposed
   as a rejected alternative ("detached tuples… for no extra speed"); measurement
   falsified the "no extra speed": after step 1 the bench page was still ~1–2 s, nearly
   all ORM hydration and JSON decoding, and plain rows took it to ~0.06 s. Detection is
   duck-typed, so its callers did not change; the `subscriptions.py` docstrings now state
   the plain-row contract.
3. `tests/test_merchant_groups.py::test_page_query_count_does_not_grow_with_transactions`
   (both routes) asserts the same SELECT count for 20 and 200 transactions across
   distinct merchants on a warm index (`used_index` asserted True); it failed on the
   pre-fix code (28 vs 208 SELECTs). Rejected: `expire_on_commit=False` globally.

**B. Monthly total — pure logic in `app/bills.py`**, no schema change:

1. `MONTHLY_FACTOR` (weekly 52/12, biweekly 26/12, monthly 1, quarterly 1/3, annual
   1/12); `ESTIMATE_PERCENTILE = 0.75`; `ESTIMATE_WINDOW_DAYS = 365`.
2. `_percentile(values, q)` — linear interpolation at position `q*(n-1)`, Decimal
   preserving.
3. `_monthly_estimate(txns, cadence)` — occurrence = one date, amount = sum of that
   date's positive charges (refunds ignored); occurrences in the 365 days ending at the
   latest one, exclusive of the far end (`d > cutoff`, so 12 monthly occurrences); P75 ×
   factor, quantized to cents ROUND_HALF_UP; `0.00` when there are no positive charges.
4. `_is_transfer(txns)` — a strict majority of the stream's **categorized** rows
   (`category` or `category_detailed` set) have a `TRANSFER*` primary or a
   `LOAN_PAYMENTS_CREDIT_CARD_PAYMENT` detailed category; uncategorized rows abstain (a
   review fix: old uncategorized autopay history must not outvote its categorized rows),
   and a wholly uncategorized stream is not a transfer. Other `LOAN_PAYMENTS` count —
   a deliberate divergence from knowledge 008.
5. `detect_bills_from_groups` adds `monthly_amount` and `excluded_reason` (first of
   `inactive`, `annual`, `transfer`; else `None`) to every bill; detection, payment
   status, sort and membership unchanged.
6. `fixed_monthly_total(bills)` → `(total, count)`, summing the rounded per-bill figures.
7. `routes.bills()` passes `fixed_total` / `fixed_count`; `bills.html` gains a "Fixed
   bills · $X / month" card (count, exclusions, "75th percentile" note) and a **Per
   month** column (header tooltips: Typical = median, Per month = P75 of the last year);
   uncounted rows show the figure muted with "not counted: <reason>".
8. Test fixtures: `FakeTxn` (test_bills, test_subscriptions) gained default-`None`
   `category` / `category_detailed`; `_persist` in test_merchant_groups copies them; the
   bills index-vs-in-memory parity test also compares `monthly_amount` and
   `excluded_reason`.

### Candidate approaches considered (monthly total)

- **A (chosen — panel 3/3) — pure estimate on detected streams, P75 over the last
  12 months, sub-annual cadences only in the total.** As above.
- **B — simple mean (or median) per bill, all active cadences including annual.**
  Rejected: the mean does not lean high for utilities and the median leans neither
  way; including annual counts tax payments and one-off purchases.
- **C — A plus a persisted per-bill include/exclude toggle.** Most accurate.
  Rejected for this unit: table + Postgres-only migration (knowledge 017), a POST
  endpoint and fetch JS (knowledge 012/019), and a stable bill identity —
  `MerchantGroup` ids are recreated on an algo-version rebuild (knowledge 029/031).
  Follow-up candidate.
- Estimator alternatives inside A: `max(mean, median)`, `mean + 0.5σ`, max. P75 is
  robust to one outlier, equals the price for fixed bills, leans high otherwise.

## Success criteria

1. With the merchant-group index already warm (`update_index()` run and
   committed before counting, and `groups_for_detection()` reporting
   `used_index=True`), `GET /bills` and `GET /subscriptions` each issue the same
   number of SQL statements for 20 seeded transactions as for 200, spread across
   distinct merchants in both runs (a test with a `before_cursor_execute` counter
   proves it for both routes), and that test fails on the pre-fix code.
2. A monthly fixed $15.00 bill has `monthly_amount == Decimal('15.00')` and
   `excluded_reason is None`.
3. A monthly variable bill with 12 occurrences in its last year, built with a
   right-skewed amount set, has `monthly_amount` equal to the hand-computed
   linear-interpolation P75, which is greater than the stream's median `amount`.
4. Occurrences more than 365 days before a stream's last charge do not affect its
   `monthly_amount`; two charges on one date count as one occurrence of their sum;
   a negative (refund) row in a stream does not lower `monthly_amount`; a stream
   with a single in-window occurrence returns that amount × factor.
5. Cadence factors: weekly $100 → `433.33`; biweekly $100 → `216.67`; quarterly
   $90 → `30.00`; annual $120 → `10.00`.
6. `excluded_reason` is `'inactive'` for an inactive stream (including an inactive
   annual one), `'annual'` for an active annual stream, `'transfer'` for an active
   monthly stream that is majority `TRANSFER_OUT` or
   `LOAN_PAYMENTS_CREDIT_CARD_PAYMENT`, and `None` for an active monthly
   `LOAN_PAYMENTS_MORTGAGE_PAYMENT` stream and for a null-category stream.
7. `fixed_monthly_total` returns the sum of the counted bills' `monthly_amount` and
   their count.
8. A `/bills` route test with DB rows renders the total and the Per month column,
   and an uncounted row shows its reason.
9. Existing bills/subscriptions tests pass unchanged; the full suite passes
   (`uv run pytest`).

## Open Questions

Interpretation choices made without asking (autonomous run); each is cheap to redirect:

- **Annual streams are excluded from the total** — the 2-occurrence annual bucket
  is too noisy in real data. Genuine annual fees are under-counted.
- **Interest charges are intentionally counted** — they recur monthly and cost
  money while a balance is carried. A per-bill toggle (C) is the fix if unwanted.
- **Inactive streams are excluded**, even ones that are probably just late
  (a monthly charge 47 days late reads as inactive); this is the existing `active` rule.
- **Known limitations:** P75 lags a price increase by ~3–4 months of a 12-month
  window; weekly/biweekly streams carry a large factor (52/12), so a weekly false
  positive inflates the total; a fuzzy-grouping false-positive monthly stream
  counts; rent paid by Zelle and tagged `TRANSFER_OUT` would be dropped as a
  transfer; a card payment with a null category would count (none appear in
  production's bills today). The visible per-row reasons keep each of these
  inspectable; there is no override (C).
- Production speed after the fix is predicted, not measured, until deploy; the
  final report re-times production `/bills` and `/subscriptions`. If either still
  takes more than a few seconds, a second cause exists and is reported, not
  guessed at (the next suspect is `grouped_transactions()` loading full ORM rows,
  JSONB columns included).
