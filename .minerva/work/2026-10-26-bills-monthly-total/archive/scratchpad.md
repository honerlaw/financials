# Scratchpad: bills-monthly-total

> **Ephemeral working memory.** Most of what lands here is noise — small
> decisions that don't matter, dead ends, momentary confusion. At feature
> completion, run `minerva:promote`: significant items get promoted to
> `.minerva/knowledge/`, `proposal.md` gets updated to match reality, and
> the raw scratchpad is archived.

## Decisions 2026-10-26
- [solo] in-flight pre-flight: no collision — no open PRs; in_flight units 014/020/022 are digest/due-date work (adjacent at most); peer messaging skipped (no user authorization); no open issue matches (open followups #28/#34/#40/#41/#46 are unrelated)
- [panel — 3/3 accept, 3 with fixes] approach: option A — P75 of last-12-months per-occurrence amounts × cadence factor; total counts active weekly/biweekly/monthly/quarterly non-transfer streams (tier: panel — genuine ambiguity: user left the estimator open, A vs C trade-off; parallel wave)
    - fix (all): define estimator inputs — positive amounts only, same-day charges summed as one occurrence (matches cadence dedup), 1–2-sample behaviour, window anchored on last charge
    - fix (skeptic/arbiter): state transfer exclusion depends on Plaid categories, null = not a transfer, add null-category test; state deliberate divergence from knowledge 008 (only card payments excluded; mortgage/car/student loans count); category = primary, category_detailed = detailed
    - fix (all): known-limitations list (weekly factor, annual under-count, no override, Zelle rent, fuzzy false positives); explicit excluded_reason precedence; total = sum of rounded rows; Typical (median) vs Per month (P75) header note
- [reviewed — clean] whole-proposal (first wave): Skeptic accepted; flagged transfer-tagged rent, annual under-count, mixed-sign amounts — all folded via the approach panel's fixes; answered the knowledge-tension doubt: no violation of 003/008 (tier: reviewer — not provably small; knowledge-tension clause routed provisionally on the approach panel; parallel wave)
- [reviewed — clean] scope check (restart): one unit, one PR covering the perf fix + the total; Skeptic accepted, noted-but-dismissed: perf fix as its own first commit (adopted), test must seed distinct merchants (adopted into criterion 1), phasing to verify prod speed first (dismissed — both ship in the same run) (tier: reviewer — user's mid-intake perf ask added a second concern, so solo's single-surface clause fails)
- [reviewed — clean] whole-proposal (restart): re-reviewed because the scope change rewrote ## Goal and ## Success criteria (perf goal added); Skeptic accepted; noted: criterion 1 must count on a warm index and assert used_index (written into criterion 1 as a test-design clarification, decision unchanged), production speed-up is a prediction (post-deploy re-time + named next suspect added to Open Questions) (tier: reviewer — parallel wave restart)
- [reviewed — clean] completion verification: Verifier reproduced all 9 criteria, including criterion 1's pre-fix failure in a temp copy at aaf2309 (28 vs 208 SELECTs); named the plain-row return type as the one contract change beyond the proposal, consumed only by the two routes (tier: reviewer floor — panel predicate does not hold: groups_for_detection's only consumers are routes.bills/subscriptions inside this unit; code review dispatched alongside)
- [solo] review triage: 7 FIX / 0 SUGGEST / 0 IGNORE (tier: default-solo row — every finding had a writable failure scenario or was documentation for touched behaviour, so FIX dominated; none had two defensible dispositions)
- [solo] replan-vs-FIX: finding 7 (proposal lists "detached tuples" as rejected, but 0093e51 does it) is not a load-bearing divergence — Goal, Success criteria and user-visible behaviour unchanged; the rejection's stated reason ("no extra speed") was falsified by measurement (1.9 s → 0.06 s), so promote rewrites ## Approach to what shipped (tier: no panel convened — the main model judged no load-bearing divergence is suspected; noted for promote to audit)
- [solo] promote partition: 2 PROMOTE (bug: commit-before-detection N+1; decision: fixed monthly total) / 2 MERGE (plain-row detection; review fixes to window + transfer vote) / 3 DISCARD (load_only intermediate attempt, whitespace-sensitive assertion, bench scripts) / 1 TODO (tier: default-solo row — no entry had two defensible buckets)
- [solo] TODO disposition: per-bill include/exclude override (approach C) → seed new proposal, surfaced in the final report; not an issue — a feature, no failure scenario, below the deferral bar (tier: default-solo row)

## Work notes
- Root cause of the 20 s /bills: routes commit after groups_for_detection() and before detection → expire_on_commit → one lazy SELECT per transaction (7,505 queries on a 7,500-row synthetic Postgres). Commit after detection: 5 queries, 3.04 s → 0.19 s. Bench scripts lived in the session scratchpad (bench.py, fixcheck.py).

## Review triage 2026-10-26
Local-diff mode (fresh-context subagent; no PR yet). Minerva audit: spec fidelity met (Verifier); one approach extension (plain rows) recorded above; no knowledge violation found.
1. [medium] app/bills.py `_is_transfer` — uncategorized history outvotes card payments → FIX: uncategorized rows abstain; test_uncategorized_history_does_not_outvote_card_payments
2. [low] app/bills.py inclusive 365-day cutoff keeps 13 monthly occurrences → FIX: exclusive; test_window_holds_twelve_monthly_occurrences
3. [low] tests/test_bills.py refund test vacuous → FIX: direct _monthly_estimate test that fails without the filter
4. [low] parity test ignores new fields; _persist drops categories → FIX: compares monthly_amount/excluded_reason; _persist copies categories
5. [low] subscriptions.py docstrings say Transaction rows → FIX: documents plain rows + _DETECTION_COLUMNS
6. [low] dead FakeTxn category params in test_subscriptions → FIX via 4 (now carried into _persist)
7. [low] proposal names the shipped change as rejected; query-test docstring blames only commit order → FIX: test docstring now; proposal ## Approach at promote
