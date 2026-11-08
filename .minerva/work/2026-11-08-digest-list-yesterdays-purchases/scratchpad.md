# Scratchpad: 2026-11-08-digest-list-yesterdays-purchases

> **Ephemeral working memory.** Most of what lands here is noise — small
> decisions that don't matter, dead ends, momentary confusion. At feature
> completion, run `minerva:promote`: significant items get promoted to
> `.minerva/knowledge/`, `proposal.md` gets updated to match reality, and
> the raw scratchpad is archived.

## Decisions 2026-11-08
- [reviewed — clean] scope check: one unit, one PR (tier: reviewer — touches spending.py/notifications.py/two tests/A2P doc, not single-surface; existing-interface doubt about the A2P-coupled SMS body passed to the Skeptic, which answered no: a repo-owned, documented regenerate-together process that unit 2026-10-12 followed; parallel wave). Noted, not load-bearing: name the A2P re-file in the PR body and knowledge entry; pin duplicate lines; restate the 2026-10-12 residuals; supersede only decision 3. All adopted as wording/tests
- [reviewed — clean] approach: A, a full purchases list with a fixed 15 cap and `+N more`. Rejected: B, dynamic fit (couples the section to every other section's length; realistic days fit); C, a multi-SMS split (dedup and partial-failure semantics, A2P "one message"); D, keep By category (contradicts "simply") (tier: reviewer — not provably small; interface doubt passed to the Skeptic, which answered no; parallel wave). Noted, not load-bearing: be honest that the cap is sized for 8 cards while ~25 lines fit on the user's 2–3; the UCS-2 segment cost; is_spend reading stated. Adopted as wording
- [reviewed — clean] whole-proposal: sound (tier: reviewer; parallel wave; no restart, because scope and approach were approved as drafted). Noted, not load-bearing: more stale docstrings (yesterday_lines, DaySpend, day_spend), the A2P Notes paragraph, test helpers, why largest-first, and that criterion 7 is a manual check. Adopted as wording

## Work notes
- Measured worst case (8 long-named cards all `(reconnect needed)`, five-digit week totals, 30 purchases with 60-char labels at $9,999.99): 1,531 chars, under 1,600 with ~70 to spare. The proposal's ~1,410 estimate left out the reconnect suffix (8 × 19 chars). Same 30 purchases with 3 cards: 1,167. The code comment carries the measured figure.
- A2P samples regenerated with a scratchpad script that calls `digest_body` (synthetic chains/amounts only, not committed). Sample 1 now has 7 purchases, including a duplicate Starbucks line. Sample 2 is a one-purchase day (it was two purchases with `Over $100: none`).
- `DaySpend` lost `large` / `by_category`, and `day_spend` lost the `large_over` param. No readers outside notifications.py and the tests (grep).
