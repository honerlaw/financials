# The digest's Yesterday section lists every purchase, not just those over $100

**Date**: 2026-11-08
**Type**: decision
**Theme**: daily-digest
**Summary**: Yesterday lists every purchase, largest first, capped at 15, with a length backstop.
**Context**: .minerva/work/2026-11-08-digest-list-yesterdays-purchases (see git history if the worktree has been cleaned up)

## Context

Since unit 2026-10-12 the digest's `Yesterday — <day>` section printed a `N purchases: $X`
summary, then only the purchases **over $100** (top 10 plus `+N more`), then a
`By category` breakdown (top 5 plus `Other`). See
[[2026-10-12-decision-digest-credit-cards-and-yesterday]], decision 3. The user asked for it
to "simply list all of the transactions we made in the last day". The small purchases the
$100 filter hid (coffee, gas, groceries) were the ones they wanted to see.

## Finding

1. **One flat list replaces both blocks.** After the summary line, the section prints one
   `label: $X.XX` line per purchase, largest first, with ties broken by label. Only dates are
   stored, not times of day, so a chronological order is not available. `DaySpend` is now
   `(day, count, total, purchases)`. `large`, `by_category`, `LARGE_PURCHASE`, the
   `large_over` parameter, `category_name`, `LARGE_LIST_MAX` and `CATEGORY_LIST_MAX` were
   deleted, because nothing else read them. Two purchases at one merchant are two lines;
   nothing is grouped.
2. **"Every purchase" means the one spend definition.** The list uses `spending.is_spend`,
   the definition the summary line already counted. Refunds and other inflows, transfers and
   credit-card payments are not listed. Pending purchases are listed. The list keys on the
   purchase date (`authorized_date or date`), and the single transaction query is unchanged.
3. **A fixed cap of `PURCHASE_LIST_MAX` = 15, then `+N more`.** The summary line still counts
   and totals every purchase. The cap is sized for 8 cards with labels of about 30
   characters, all flagged `(reconnect needed)`, five-digit week totals, and 15 lines of
   32-character labels at $9,999.99. That worst case measured 1,531 characters, pinned by
   test. Dynamic fitting, which would list as many purchases as fit, was rejected: it couples
   the section to every other section's length, and a realistic day has fewer than 15
   purchases. Accepted cost: with the user's 2–3 cards about 25 lines would fit, so a day
   with 16–25 purchases is truncated when it need not be.
4. **`digest_body` enforces `BODY_MAX` = 1600 itself.** Card lines are uncapped. Review
   measured that 9 short-named cards already reach exactly 1,600 characters, and 8
   realistic long Plaid names reach 1,819. That exposure existed before this unit too. So
   `digest_body` builds the fixed head and tail of the message once, and if the body is too
   long it lists one fewer purchase at a time, so `+N more` grows. The fixed cap stays the
   primary rule; the backstop only ever lowers it. The one case left over-long is a body
   that does not fit even with no purchase lines, which takes about 25+ long-named cards.

## Implications

- **The A2P samples and campaign description changed again.** The three samples in
  `docs/twilio-a2p-campaign-resubmission.md` were regenerated from `digest_body`: a
  seven-purchase day with a duplicate line, a one-purchase day, and an empty day. The
  campaign description now reads "how many and their total, followed by each purchase and
  its amount". If the campaign is already filed, the samples and description must be
  re-submitted in Twilio. The doc's own rule is that a filed sample which no longer matches
  live traffic is a violation, and production deploys on every push to `main`.
- **Message length now varies with activity.** It is about 25 characters per purchase line,
  and the body is UCS-2 (67 characters per segment). A busy day bills several more segments
  than before, which costs pennies.
- **The 2026-10-12 residuals still hold, and are now more visible.** A posted row with no
  `authorized_date`, or one whose `authorized_date` differs from its pending row's, can be
  listed a second time under its posting day. A purchase first synced after its day has
  passed is never listed. Before, those rows only showed when they were over $100; now every
  one shows as its own line.
- **Decisions 1, 2 and 4–6 of 2026-10-12 still stand.** Those are the cards-only balance
  block, the removal of net worth, one spend definition and one query, purchase-date keying,
  and the required `digest_body` arguments.

## Related

- [[2026-10-12-decision-digest-credit-cards-and-yesterday]] — extends: replaces decision 3's Yesterday shape (over-$100 list + by-category) with a full purchase list; its other decisions stand.
- [[2026-10-12-constraint-plaid-date-is-the-posting-date]] — builds on: the list keys on the purchase date, and that entry's residuals now show on every row.
- [[016-decision-daily-digest-notifier]] — see also: the 1600-character limit and the UCS-2 note this cap and backstop answer to.
- [[022-decision-digest-four-week-spend-history]] — see also: the one-query rule and required-argument rule, both kept.
