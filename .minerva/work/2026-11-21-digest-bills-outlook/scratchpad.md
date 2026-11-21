# Scratchpad: digest-bills-outlook

> **Ephemeral working memory.** Most of what lands here is noise — small
> decisions that don't matter, dead ends, momentary confusion. At feature
> completion, run `minerva:promote`: significant items get promoted to
> `.minerva/knowledge/`, `proposal.md` gets updated to match reality, and
> the raw scratchpad is archived.

## Decisions 2026-11-21
- [solo] pre-flight: no collision — 014/020/022 report in_flight only from legacy un-promoted markers (all Status: Shipped, last touched Jul–Aug); remote unit branches all MERGED (#56 #62 #66 #67 #68); no open PRs; peer messaging not authorized, skipped (hardcoded check, not tiered)
- [solo] open-issue match: no match — #58 (drifting-day false "Unpaid" on /recurring) is adjacent, not the same change (hardcoded check)
- [reviewed — clean] scope check: one unit, one PR, unphased (tier: reviewer — fails solo "single surface"; parallel wave). Skeptic non-blocking notes: commit ownership of index warm-up, `load_rules` should take a session — both taken into the approach fold
- [reviewed — folded] approach: B (cadence-aware month outlook); Skeptic C1 quarterly `last_date + 91` puts a 1st-of-month bill a month early → calendar-month arithmetic; C2 "On track for" misleads → "Bills this month"; C3 dropped connection inside a savepoint poisons the later DailyDigest write → run last + full rollback; C4 commit ownership/cost stated; C5 keep PURCHASE_LIST_MAX=15 and amend 2026-11-08 d3 (backstop covers pathological case); C6 skip-prone weekly residual listed (tier: reviewer — scrutiny: knowledge tension 022 d3 / 2026-11-08 d3, existing interface change A2P body, ambiguity monthly window; parallel wave). Rejected: A (payment_status as-is, wrong for weekly/quarterly), C (monthly_amount − paid, false residue on variable bills), D (budget/Yesterday changes, unasked)
- [rechecked — clean] approach: fold-audit confirmed C1–C6 addressed; new low notes (commit expiry, SQLite can't prove PG abort, widened fetch must keep 4-week filter) → implementation checks
- [reviewed — clean] whole-proposal (first wave): accept; non-blocking notes on one-query test wording, cap cut, label, fallback total meaning, A2P sequencing (tier: reviewer; parallel wave) — result discarded by restart
- [reviewed — clean] whole-proposal (restart): re-reviewed after the approach fold rewrote ## Goal ("Bills this month" label, fallback line) and ## Success criteria; accept with non-blocking notes (Bills = detected recurring; db.session vs session; send_digest_now commits warm-up; weekly-today residual) → folded into Open Questions (tier: reviewer — scrutiny: knowledge tension, existing interface change, ambiguity)

## Work notes
