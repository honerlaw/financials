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
- [reviewed — clean] completion verification: Verifier reproduced criteria 1–5, 7; criterion 6 'unsure' only because its sandbox denied flask db commands — reproduced in-session (stamp → upgrade → UNIQUE autoindex → downgrade, single head) (tier: reviewer floor — no interface beyond the approved new table/endpoint; code review dispatched alongside)
- [solo] review triage: 3 FIX / 0 SUGGEST / 0 IGNORE — (1) essential=1 now takes exactly one key, so the IntegrityError rollback can't discard a second insert; (2) keys over 255 chars are omitted at construction (no toggle instead of a 400); (3) test for the IntegrityError branch. Minerva audit: no findings (027 checked — .btn-success follows .btn at equal specificity) (tier: default-solo row — each low finding had a writable failure scenario and a small fix; none had two defensible dispositions)
- [solo] promote partition: 1 PROMOTE (decision entry 2026-11-07-decision-essential-marks-keyed-by-stream, absorbing the partial-template gotcha and migration verification) / 5 MERGE INTO PROPOSAL (hidden split, .btn-success, 3 review fixes) / 1 DISCARD (check-stream fixture count) / 0 TODO (tier: default-solo row — no entry had two defensible buckets)

## Work notes
- Toggle macro lives in `app/templates/_essential_toggle.html` (not inline in recurring.html): `get_template_attribute` on recurring.html evaluates the whole page module and fails on undefined page vars, so the empty-keys criterion is tested against the partial.
- The seeded check stream (Check #1001, monthly 310.00) is detected as a counted bill without any rule, so the route fixture has 4 counted bills.
- Essential split is hidden when no expense is counted (no "0 of 0"); asserted in `test_recurring_page_empty_state`.
- Added `.btn-success` to app.css (mirrors `.badge-success`); no existing class gave a green button.
- Migration b8d4e2f7a9c1 verified in isolation (knowledge 017): stamp a3e6c1d8f205 → upgrade creates table + UNIQUE(stream_key) autoindex → downgrade drops it; single head.

## Review triage 2026-11-07
- FIX (low) routes.py set_essential: multi-key essential=1 + IntegrityError rollback discards all inserts → restricted essential=1 to exactly one key.
- FIX (low) bills.py _merchant_keys: key could exceed String(255) → unmarkable 400 → over-long keys omitted (stream gets no toggle). ESSENTIAL_KEY_MAX_LENGTH moved to bills.py, imported by the route.
- FIX (low) tests: IntegrityError branch untested → test_mark_saved_concurrently_is_already_essential (monkeypatches the pre-check). SQLite cannot show Postgres's aborted-transaction behaviour (knowledge 033); the rollback covers it.
