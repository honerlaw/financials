# Proposal: 2026-11-08-digest-list-yesterdays-purchases

**Date**: 2026-11-08
**Status**: Draft

## Goal

The user's request (verbatim): "Can we make sure to simply list all of the transactions we made in the last day on the daily text that goes out".

Today the daily digest SMS (`app/notifications.py`, `digest_body` → `yesterday_lines`) reports the previous local day as: a `N purchases: $X` summary, then only purchases **over $100** (capped at 10 + `+N more`), then a `By category` breakdown (capped at 6). Change the `Yesterday — <day>` section so it simply lists **every purchase made yesterday**, one line each (`<merchant>: $12.34`), under the existing summary line. The `Over $100` itemization and the `By category` breakdown are removed. Both send paths (7am scheduled digest and the dashboard's "Text me this" button) change together via the shared `_digest_parts` seam.

Target section shape:

```
Yesterday — Sun Oct 11
6 purchases: $287
Whole Foods Market: $142.18
Shell: $48.20
Chipotle: $31.75
Starbucks: $28.40
CVS: $22.17
Amazon Marketplace: $14.30
```

Unchanged: everything else in the message, `No purchases.` on an empty day, the spend definition, the purchase-date keying, the single transaction query.

"Every purchase" has two deliberate limits, stated so nobody reads them as bugs:

- **What counts as a purchase.** The list uses the digest's one spend definition (`spending.is_spend`), the same one the summary line already counts. Refunds and other inflows, transfers and credit-card payments are not listed. A card payment is money moving between the user's own accounts, not something "we made". Pending purchases are listed.
- **A length cap.** At most 15 lines, then `+N more`, because Twilio rejects a body over 1600 characters. This is sized for the worst case (8 long-named cards). With the user's 2–3 cards, about 25 lines would actually fit, so a day with 16–25 purchases is truncated when it need not be. That is the price of a fixed cap over dynamic fitting (option B below), and it was accepted. The summary line always counts and totals every purchase.

Several purchases at one merchant (two coffees) are separate lines, not grouped.

## Why

The user wants to see what was actually bought yesterday, not a threshold-filtered subset plus category totals. Small purchases (coffee, gas, groceries) are exactly what the >$100 filter hides.

## Approach

**A — replace `large` + `by_category` with one full `purchases` list, with a fixed length cap (recommended).**

- `app/spending.py`: `DaySpend` becomes `(day, count, total, purchases)` where `purchases` is `[(label, amount)]` for **every** `is_spend` row whose `purchase_date` is the day, largest first, ties by label (label = `merchant_name or description`, as today). `LARGE_PURCHASE`, the `large_over` parameter and `by_category` are deleted (no other readers — grep-verified).
- `app/notifications.py`: `yesterday_lines` prints header, `N purchase(s): $X` (whole dollars, as today), then one `label: $X.XX` line per purchase (label truncated to 32 chars, as today). If there are more than `PURCHASE_LIST_MAX` = 15 purchases, the first 15 are shown and a `+N more` line follows (the summary line above still counts and totals all of them). `category_name`, `LARGE_LIST_MAX`, `CATEGORY_LIST_MAX` are deleted.
- Why a cap at all: Twilio rejects a body over 1600 characters and the day's digest is lost (knowledge 016 / 2026-10-12). Measured: the worst-case non-Yesterday part of the body (8 cards with long names and 5-digit balances) is ~730 chars; a worst-case purchase line is ~44 chars (32-char label + `: $9,999.99` + newline); 15 lines ≈ 660 → ~1,410 total, leaving margin. With the user's realistic 2–3 cards the body without Yesterday is ~480 chars. A realistic household day is well under 15 purchases, so in practice every purchase is listed.
- Order is largest first, ties by label. Only dates are stored, with no time of day, so a chronological order is not available.
- Message cost: the body is already UCS-2 (because of `—`/`·`/`••`), so at 67 characters per segment a long day bills more segments, about 21 at the worst-case 1,400 characters. That is pennies, and accepted in the same way as the existing UCS-2 note in knowledge 016.
- Tests: update `tests/test_spending.py` day_spend tests and `tests/test_notifications.py` Yesterday tests (pure + through both send paths); replace the worst-case length test with one using 30 purchases with 60-char labels at $9,999.99 and 8 worst-case cards.
- Docs: regenerate the three sample messages in `docs/twilio-a2p-campaign-resubmission.md` from `digest_body` (the doc's own rule: samples are generated, not hand-written, and must match live traffic), update the campaign description's content list ("each purchase over $100, and spending by category" → "each purchase and its amount"), and update the coverage paragraph after the samples (remove `Over $100: none` / `Other` category variants; `+N more` remains the rare variant). Update every stale prose mention of "over $100" or "by category": the module docstrings of `app/notifications.py` and `app/spending.py`, the `yesterday_lines`, `DaySpend` and `day_spend` docstrings, and the doc's Notes and coverage paragraphs. The samples must cover a multi-purchase day, a one-purchase day and an empty day, with `+N more` named as the remaining rare variant.
- Knowledge: a new decision entry that supersedes **only decision 3** (the Yesterday shape) of `2026-10-12-decision-digest-credit-cards-and-yesterday`, and restates that entry's known residuals. A posted row without `authorized_date` can be shown again under its posting day. A purchase first synced after its day is never listed. Listing every purchase makes the first residual more visible.
- The A2P re-file is called out in the PR description and the knowledge entry, not only in the final report. The doc's step 5 says a filed sample that no longer matches live traffic is a violation, and production deploys on every push to `main`.

**Considered:**

- **B — dynamic fit.** List as many purchases as fit under the 1600-char budget given the rest of the message, then `+N more`. Lists more on a very busy day, but couples `yesterday_lines` to the length of every other section and makes the cap untestable as a constant. Rejected: realistic days fit under 15 anyway; complexity for no practical gain.
- **C — split long digests across multiple SMS.** Rejected: dedup is one `DailyDigest` row per (day, recipient), partial-send failure semantics get murky, and the A2P campaign states one message per morning.
- **D — keep `By category` and just drop the $100 threshold.** Rejected: the user said "simply list"; the category block is the noise they're asking to remove.

## Success criteria

1. For a day with purchases, the `Yesterday` section is exactly: header, `N purchase(s): $X`, then one `label: $X.XX` line per `is_spend` purchase on that `purchase_date`, largest first, ties by label. No `Over $100…` or `By category` line appears anywhere in the digest. Pinned by pure tests on `yesterday_lines` and a through-the-send-path test on real transactions.
2. A purchase of any size (e.g. a $4.50 coffee) is listed, and two identical purchases at one merchant are listed as two lines. Pinned by tests.
3. More than 15 purchases → exactly 15 lines then `+N more`, where N is the hidden count; the summary line still counts/totals all. Pinned by test.
4. A worst-case digest (8 long-named cards with 5-digit balances, 30 purchases with 60-char labels at $9,999.99, 5-digit week totals) is under 1600 characters. Pinned by test.
5. Unchanged behaviour still pinned by the existing tests: `No purchases.` on an empty day; refunds, transfers/card payments and removed rows excluded, pending included; purchase-date keying (once across pending→posted); one transaction query; scheduled and manual bodies identical.
6. `LARGE_PURCHASE`, `DaySpend.large`, `DaySpend.by_category`, `category_name`, `LARGE_LIST_MAX`, `CATEGORY_LIST_MAX` no longer exist in `app/` or `tests/`.
7. The three A2P sample messages in `docs/twilio-a2p-campaign-resubmission.md` are regenerated from `digest_body` and match its output (checked manually by regenerating them with a script, as before); the campaign description no longer mentions "over $100" or "by category".
8. `uv run pytest` passes.

## Open Questions

- Whether the live A2P campaign must be re-submitted with the new samples/description is an operational step outside the repo (as it was for unit 2026-10-12). The doc is updated; the final report flags it for the user.
