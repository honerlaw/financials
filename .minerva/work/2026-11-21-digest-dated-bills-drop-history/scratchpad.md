# Scratchpad: digest-dated-bills-drop-history

> **Ephemeral working memory.** Most of what lands here is noise — small
> decisions that don't matter, dead ends, momentary confusion. At feature
> completion, run `minerva:promote`: significant items get promoted to
> `.minerva/knowledge/`, `proposal.md` gets updated to match reality, and
> the raw scratchpad is archived.

## Decisions 2026-11-21
- [solo] pre-flight: no collision — no open PRs; remaining remote unit branches all merged (incl. #69); no matching open issue (hardcoded checks)
- [reviewed — clean] scope check: one unit, one PR (tier: reviewer — fails solo "single surface"; parallel wave). Non-blocking: add an A2P provenance line; rewrite (not delete) the ordering test; legacy index.md/overview.md mention `Last 4 weeks` — left alone (promote is add-only)
- [reviewed — clean] approach: A, inline the range into each label (tier: reviewer — scrutiny: existing interface change A2P body/digest_body/recent_week_spend, knowledge tension 022 + fetch window, ambiguity week line & spend end date; parallel wave). Rejected: B (one dated header — leaves ends implicit), C (relabel the week line — not asked). Non-blocking: pin due-window in a test; doc/docstring wording
- [reviewed — folded] whole-proposal: C1 "Due Nov 21–30" asserted a start date `_remaining_charges` enforces only for weekly/biweekly → "Still due by Nov 30"; C2 "Spent Nov 1–21" end date unenforced → month_spend and month_outlook bounded to ≤ today; C3 one dash style (unspaced, same-month only); C4 fetch-floor invariant stated (tier: reviewer — same scrutiny clauses; parallel wave). Restart check: scope and approach clean, no fold → first-wave result stands
- [rechecked — clean] whole-proposal: fold-audit confirmed C1–C4 addressed; low notes ("Unchanged" wording, assert paid count for future-dated row) → folded into proposal

## Work notes
