# Scratchpad: digest-card-balances-and-yesterday

> **Ephemeral working memory.** Most of what lands here is noise — small
> decisions that don't matter, dead ends, momentary confusion. At feature
> completion, run `minerva:promote`: significant items get promoted to
> `.minerva/knowledge/`, `proposal.md` gets updated to match reality, and
> the raw scratchpad is archived.

## Decisions 2026-10-12
- [hardcoded check — clear] pre-flight: no collision — units 014/020/022 flagged by in_flight are shipped (PRs #30, #38 merged; 014 shipped), adjacent digest work only; no open PRs; peer discovery skipped (no authorization); open-issue match: none (#37 is adjacent — becomes moot, closed by this unit) (tier: hardcoded check, no trigger)
- [reviewed — clean] scope check: one unit, one PR, no phases (tier: reviewer — not provably small, multi-file surface; parallel wave). Skeptic accepted; noted _week_totals must expose the yesterday aggregate (folded as write-up into Approach 1) and the 024 supersession at promote (Approach 8) — neither load-bearing for scope
- [reviewed — clean] approach: A — pure aggregation over the existing single fetch; rejected B (SQL aggregates: third spend definition, extra queries) and C (keep exclusion list for cards: dead config) (tier: reviewer — interface-clause doubt on removing NET_WORTH_EXCLUDED_ACCOUNTS passed to the Skeptic; it answered no: single in-repo reader, var unset in prod per #37, read via getenv default; parallel wave). Noted-but-dismissed: SMS length — worst case estimated ~1,480 chars < 1600; handled as a length success criterion via the whole-proposal fixes
- [panel — 3/3 accept, 3 with fixes] whole-proposal: accepted (tier: panel — genuine-ambiguity doubt: over-$100/category window yesterday vs week; parallel wave; no restart — scope and approach unchanged)
    - fix (arbiter/skeptic): Open Questions gain "net worth removed outright" and "transactions = purchases (is_spend)"
    - fix (arbiter/skeptic): promote step to write a decision entry superseding 024; #37 verified open
    - fix (arbiter/skeptic): category lines capped at top 5 + Other; worst-case length criterion added; truncation form stated
    - fix (proponent): "a week total printed in the text" (Saturday falls in history week)
    - fix (arbiter/skeptic): opt-in/terms wording drift called out explicitly; A2P samples cover no-purchases and none-over-$100 days
    - fix (arbiter/skeptic): negative per-card balance format specified (`$-X`, unchanged) and tested; pending inclusion stated as deliberate (sync flags the pending row removed — verified app/sync.py:_mark_removed)
    - fix (proponent): deletion targets named; whole-dollar vs cents rounding accepted
