# Scratchpad: subscriptions-view

> **Ephemeral working memory.** Most of what lands here is noise — small
> decisions that don't matter, dead ends, momentary confusion. At feature
> completion, run `minerva:promote`: significant items get promoted to
> `.minerva/knowledge/`, `proposal.md` gets updated to match reality, and
> the raw scratchpad is archived.

## Panel decisions 2026-06-07
- [user-directed] propose-phase gates (scope, approach, whole-proposal): user ran manual minerva:propose with grill-plan and approved all sections directly, then directed auto continuation from the work phase
- [skipped — small] same-day duplicate handling: dedupe dates for cadence math, keep raw count (evidence: single helper in app/subscriptions.py, covered by gap math in tests)
- [3/3 accept] completion verification: all 5 success criteria honestly met, 96 tests pass (low-severity notes: "spread" wording vs MAD implementation — fixed in proposal; prefix-merge aggressiveness + no bimonthly bucket acknowledged as Open Questions tuning risks)
- [2/2 accept, arbiter skipped — quorum already secured] review triage: #1 FIX comment-only (removed-gate ownership), #2 SUGGEST (order-dependent fuzzy merge), #3-5 IGNORE (cosmetic/deliberate), #6 FIX (multi-account route-label test)

## Review finding 2026-06-07
- SUGGEST (from triage #2): name-group fuzzy merge is order-dependent and non-transitive — name groups only ever merge into entity-id-seeded or alphabetically-earlier groups via first-match `break`; they never re-coalesce transitively with each other. Distinct from (and sharper than) the general "fuzzy threshold tuning" Open Question. Revisit if real synced data shows borderline merchants landing in the wrong stream.

## Implementation notes 2026-06-07
- Detection lives in `app/subscriptions.py` as pure functions — no DB access, route passes `Transaction.query.filter_by(removed=False).all()` plus `date.today()`.
- Noise-token stripping (`com`, `inc`, …) plus digit/punct removal makes "NETFLIX.COM 866-579-7172" == "Netflix" exactly; SequenceMatcher ≥0.82 and a ≥5-char prefix rule catch the rest ("SPOTIFY USA").
- Gap-regularity rule (≥70% of gaps inside the bucket tolerance) is what rejects frequent-but-irregular merchants (groceries) whose *median* gap accidentally lands in a bucket — median-only matching was not enough.
- Amount spread uses MAD/|median| > 0.25 → a single price hike does NOT set "varies" (MAD stays 0) but card-payment-style swings do. This was the reason to use MAD instead of max-deviation.
- Route test seeds dates relative to `date.today()` — fixed dates would drift past the 1.5× inactive boundary and start flaking weeks later.

