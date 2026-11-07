# Scratchpad: essential-recurring-expenses

> **Ephemeral working memory.** Most of what lands here is noise — small
> decisions that don't matter, dead ends, momentary confusion. At feature
> completion, run `minerva:promote`: significant items get promoted to
> `.minerva/knowledge/`, `proposal.md` gets updated to match reality, and
> the raw scratchpad is archived.

## Decisions 2026-11-07
- [solo] pre-flight: no collision — in-flight-flagged units 014/020/022 are Shipped legacy units; remote branch 2026-11-06-recurring-page's PR #56 merged; no open PRs; peer discovery skipped (no authorization). Open-issue match: none (#58 adjacent — same page, drifting-day status)
- [reviewed — clean] scope check: one unit, one PR (tier: reviewer — fails solo single-surface clause: model, migration, bills, routes, template; parallel wave). Skeptic accepted; noted grant check — verified: 00a2889ed2af sets ALTER DEFAULT PRIVILEGES, no explicit GRANT needed
- [reviewed — clean] approach: B — essential_marks table keyed by rule:/merchant:/@amount stream keys; rejected A (column on RecurringRule — forces a rule, changes detection), C (pattern tags — over-match, needs form), D (display name — breaks on rename, violates 032 spirit) (tier: reviewer — introduces new table/endpoint, no existing consumer; parallel wave). Skeptic: no knowledge tension with the user-rules entry (different purpose). Dismissed: parent-key fallback for split sub-streams (would let one plan's mark cover siblings) — documented as a known consequence instead
- [reviewed — folded] whole-proposal: folded deliberate not-essential bias statement, empty-key no-toggle, exact @amount format, 500-key cap, grants note, split/merge consequences, extra criteria (zero marks, Y+Z==total, sibling, merged on→off, rule toggle, fictional fixtures) (tier: reviewer; parallel wave; no restart — scope/approach unchanged)
- [rechecked — residual folded] whole-proposal: items 2/3/7 partially and 4 not addressed (all non-load-bearing) + new concern 1 (sub-stream keys of a merged group unspecified) — folded: @amount key per grouping key, stale-form and key-reuse consequences, tests for empty keys, 255-char limit, page-level sibling

## Work notes
- Toggle macro lives in `app/templates/_essential_toggle.html` (not inline in recurring.html): `get_template_attribute` on recurring.html evaluates the whole page module and fails on undefined page vars, so the empty-keys criterion is tested against the partial.
- The seeded check stream (Check #1001, monthly 310.00) is detected as a counted bill without any rule, so the route fixture has 4 counted bills.
- Essential split is hidden when no expense is counted (no "0 of 0"); asserted in `test_recurring_page_empty_state`.
- Added `.btn-success` to app.css (mirrors `.badge-success`); no existing class gave a green button.
- Migration b8d4e2f7a9c1 verified in isolation (knowledge 017): stamp a3e6c1d8f205 → upgrade creates table + UNIQUE(stream_key) autoindex → downgrade drops it; single head.
