# Scratchpad: quick-not-recurring

> **Ephemeral working memory.** Most of what lands here is noise — small
> decisions that don't matter, dead ends, momentary confusion. At feature
> completion, run `minerva:promote`: significant items get promoted to
> `.minerva/knowledge/`, `proposal.md` gets updated to match reality, and
> the raw scratchpad is archived.

## Decisions 2026-11-08
- [reviewed — clean] scope check: one unit, one PR, no phases (tier: reviewer — new route fails solo's no-new-interface clause; parallel wave). Skeptic's approach-level concerns (guard keyed on grouping_key) carried to the approach gate
- [reviewed — folded] approach: A kept; guard changed from grouping-key containment to exact row-set equality against the server-recomputed stream, plus idempotent re-post, pattern in notice, future-matches title, ?marked int parse (tier: reviewer — introduces a new route, no existing consumer; parallel wave). Rejected: B no guard, C per-stream dismiss table, D inline per-row preview, A′ key containment
- [rechecked — residual folded] approach: R1.7 essential-mark-survives test and R2.7 action preserved partially addressed; folded the test, Decimal split_amount compare, action filter on the already-marked lookup, and a consumer check for the new `rows` key
- [reviewed — clean] whole-proposal (restart): re-reviewed after the approach fold rewrote Success criteria; notes (dedupe while stream still found → candidate loses rows to the identical saved rule, so it falls back to the form; autoescape) not load-bearing (tier: reviewer; parallel wave restart)
- [solo] mid-work: the quick form posts only the locator (`stream_key`[], `direction`, `split_amount`); label and pattern come from the located stream server-side. Routine, not a divergence: the approved Approach already says posted keys only locate the stream, and this narrows trust further. Triggered by hidden `label`/`pattern` inputs duplicating the merchant name on the page (broke name-count tests). Consequences: malformed/no-key/unknown posts redirect to /recurring (nothing to rebuild a form from) instead of the form; the "already marked" lookup matches by the rule claim's `stream_keys` (added to `_rule_entry`) rather than by posted pattern (tier: solo — single route, verified by tests in tests/test_quick_not_recurring.py)
- [reviewed — clean] completion verification: Verifier reproduced all 5 criteria (invalid-input deviation judged to honour intent; proposal wording to update at promote) (tier: reviewer floor)
- [solo] review triage: 5 FIX (notice anchor, lookup amount filter, single locate pass, missing tests, proposal drift) / 1 SUGGEST (sibling plan's essential mark lost when a split becomes whole) / 0 IGNORE (tier: default-solo row — no item had two defensible dispositions)

## Work notes
- Field is `stream_key`, not `key`: the essential toggle's forms already post `key`, and test helpers scrape `name="key"` per row.
- After quick-marking one same-amount plan, the sibling plan's rows become the whole group, so it renders as the merchant's own stream (no `· $amount` suffix) — expected, asserted in the test.
- The "taken" branch of `quick_mark_verdict` is defensive: a located stream's rows are leftovers, so a candidate taking saved-rule rows already fails row equality.

## Review finding 2026-11-08
- SUGGEST (standing fact): quick-marking one same-amount plan turns the sibling plan's rows into the whole group, so its essential key changes from `merchant:<k>@<amount>` to `merchant:<k>` and a saved essential mark on it no longer matches ("split becomes whole" is another way marks are lost, alongside the ones knowledge 2026-11-07-essential-marks lists). Undo restores it. Pre-existing keying behaviour, made easier to hit by one click.
