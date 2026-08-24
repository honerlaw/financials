# Scratchpad — 020-digest-four-week-history

## Quick decisions 2026-08-23
- [escalated to user] which four weeks: current-week-inclusive vs four completed weeks — genuine coin flip, and the SMS body is coupled to the A2P samples on file, so a wrong guess costs a re-filing. User picked four completed weeks. (Escalation 1/3.)
- [decided] scope: single work unit — one pure helper, one body change, tests, plus the A2P doc samples that are contractually coupled to the body. No decomposition.
- [decided] approach: pure `recent_week_spend` in spending.py reusing `is_spend`/`week_start`; rejected SQL GROUP BY (dialect-specific date math + a second spend definition) and reusing `weekly_budget` (month-anchored, wrong return shape).
- [decided] `digest_body(history=...)` required, not defaulted — a default turns a forgotten argument into a silently short message.
- [decided] regenerate the A2P sample messages + campaign description in this unit: the campaign has not been filed yet, and traffic must match what gets filed.
- [decided] soundness: no public interface changes beyond `digest_body`'s signature (two in-repo callers) and `_week_label` → `week_label`; no config, no schema, no migration.
- [decided] review triage: F1 (malformed `_week_totals` docstring) → FIX, applied. No other findings; spec fidelity and knowledge lenses clean.
- [decided] promote partition: one PROMOTE (the four-week-history decision), review fix MERGED into the proposal, quick decisions DISCARDed as routine, no new TODOs — the segment-count and 1600-char notes belong to unit 016's existing followups, not a new issue.

→ promoted to .minerva/knowledge/022-decision-digest-four-week-spend-history.md (2026-08-23)
