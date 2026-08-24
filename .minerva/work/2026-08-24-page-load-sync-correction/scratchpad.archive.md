# Scratchpad: page-load-sync-correction

## Balanced decisions 2026-08-24

- [escalated to user] open-issue match at intake: #44 matched the seed exactly — I filed it an hour ago from this same finding. Hardcoded ask per `issue-match.md`, fires regardless of the run's predicates. User chose "execute #44 as-is" over "adopt and extend with a corpus-wide audit of other unverified runtime claims". `**Closes**: #44` written into the proposal at creation.
- [reviewed — folded] scope check: single unit (Skeptic verdict `revise`). It found **five** sites beyond the three I had inventoried — `tests/test_sync.py`, `app/notifications.py:35`, knowledge 010, knowledge 023, and `index.md`'s catalog line. Folded all five. Notable: I had just filed #44 claiming three sites *after* tracing the bug, and still undercounted; the Skeptic's framing was that landing the unit as scoped would reproduce the exact "code fixed, record still lying" failure the issue exists to prevent. It also resolved its own uncertain flag correctly on my check: `018:45` and `notifications.py:396` say the lazy `twilio` import "stays lazy on a page load", which is about import behaviour during rendering and is *true* — not swept up.
- [reviewed — folded] approach selection: annotate-in-place per 014's precedent (Skeptic verdict `revise`; mechanism validated, scope incomplete). Folded four points: (#1) a **second** false docstring in `app/sync.py` at `_create_account_if_missing:115` that both gates had missed; (#2) the `index.md` catalog-line trap — verified in `knowledge_fix.py::plan_index`, which "preserves each surviving catalog line verbatim" and only *adds* lines for entries lacking one, so editing 016's `**Summary**` does **not** propagate and no lint check compares the two; (#4) the supersession-banner mechanism is live on entry 010 and is now named as considered-and-rejected rather than left looking overlooked; (#6) `Type: pattern`, not `bug` — no code was ever wrong at runtime, and the durable payload is the failure mode. Also folded (#5) as an authoring constraint: `DIRECTIONAL_TERMS = ("supersede", "contradict")` in `knowledge_fix.py`, so a `## Related` label containing either substring silently loses its reciprocal back-link.
- [decided] whole-proposal soundness: sound (solo gate). Prose corrections plus one test-function rename; no executable line changes, no runtime behaviour change, no public interface, no schema. Fully reversible. The one thing worth flagging to the user is extent, not direction — recorded in the proposal's Open Questions rather than spent as an escalation.
- [reviewed — folded] completion verification (pass 1): Verifier verdict `revise` — criterion 1 unmet. It found a 14th site, `016-daily-balance-digest/followups.md:13`, and the reason it mattered: `followups.md` is re-read whenever work is scoped, so the exemption I had drawn by *directory* wrongly filtered out a *live* document. Treated as a success-criteria divergence -> Phase 2.5.
- [reviewed — folded] replan acceptance: Skeptic verdict `revise` (mechanism sound, three gaps). Folded: (#1) the correction mechanism was wrong — `backfill-followups/SKILL.md` says `followups.md` files are "appended to, never rewritten", so the wiki's in-place convention does not transfer; (#2) that followup's mechanism is *fully* invalidated rather than mis-premised, so the note says so instead of implying the idea survives; (#3) the count had to propagate to five places, plus a pre-existing "10 sites, 7 files" drift. Also folded (#4) the criterion's phrasing, from name-checking `followups.md` to the general live/archival test. Its independent checks confirmed no further live site and no shadow GitHub issue carrying the same premise.
- [reviewed — clean] completion verification (pass 2, post-replan): Verifier verdict `accept` — all 9 criteria reproduced independently, counts enumerated from the diff and confirmed as 14 sites across 9 files, no 15th site, every annotation verified as an accurate quotation of the pre-change text, and no numbering collision left after the 029->034 renumber. One minor defect it raised (three "entry 029" references in `replan.md`, freshly inconsistent because they were authored in the same commit that renumbered the entry) was fixed rather than deferred.
- [decided] review triage: minerva audit clean — spec fidelity matches the proposal as replanned, and the change complies with 014's annotation convention, `backfill-followups`' append-only rule, the `DIRECTIONAL_TERMS` label constraint, and the hand-edited catalog line. The code-quality pass was recorded as not-applicable rather than skipped: the diff has **zero executable line changes** (criterion 5, verified twice), and the single test change is a rename plus docstring with a byte-identical body. There is no code to review.
- [decided] promote partition: one PROMOTE (entry 034), proposal rewritten to match what shipped, scratchpad archived. **No TODOs.** The one candidate — a corpus-wide audit for *other* unverified runtime claims — was offered to the user at intake and declined; entry 034 records the practice that would prevent a recurrence, and a standing "audit everything" issue would sit open indefinitely without adding to that.

## Coordination

`financials-a5` is mid-lifecycle on `2026-08-24-merchant-group-index` and also
edits `app/sync.py`. Confirmed disjoint by both sides and independently by the
scope Skeptic, which diffed that branch against `main`: its `app/sync.py` changes
are a new `_grouping_key_for` helper, a `merchant_key` entry in `_extract_fields`,
and an index-refresh block in `_sync_institution`'s tail — none within 30 lines of
`run_daily_sync`'s docstring. It does not touch `tests/test_sync.py` (it adds its
own `tests/test_merchant_groups.py`) or `app/notifications.py` at all. Agreed:
whoever lands second rebases; a5 explicitly said not to hold off.

**`app/notifications.py` needs care for an unrelated reason.** Its *message text*
is filed with the carrier for A2P 10DLC (knowledge 022/024), so changing what the
digest says forces a campaign re-filing. This unit edits a module docstring at
line 35 only — no message string, no builder.

## The claim, and what is actually true

`/api/sync` is POST-only, registered in `app/routes.py`, and has exactly one
caller: `triggerSync(btn)` in `app/templates/base.html`, behind a button's
`onclick`. It does spawn a background thread — that part of the record is right —
but only when the button is pressed.

Archaeology: `git show 7043b4e:app/templates/base.html` has the fetch already
inside `triggerSync`. That is the commit that introduced the templates, so there
is no revision in which the page-load sync existed. The docstring never described
reality, which rules out the reading where someone removed an auto-sync and
forgot the comment.

## Implementation notes
