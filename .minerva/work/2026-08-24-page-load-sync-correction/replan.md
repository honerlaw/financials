# Replan — 2026-08-24

## Original plan

Exempt everything under `.minerva/work/*` from correction, as historical record.
The proposal's wording: *"They record what a unit believed at the time, which is
what makes them the evidence for the propagation chain; rewriting them would
erase it."* That covered the `proposal.md` files and archived scratchpads
carrying the claim in units 012, 016 and 021.

## What changed

The completion Verifier found a 14th site and, with it, a flaw in how the
exemption was drawn: **by directory, when the property that matters is whether
the document is live.**

`.minerva/work/016-daily-balance-digest/followups.md:13` proposes, as deferred
work:

> "Add a bounded catch-up on the page-load sync path: send if no `DailyDigest`
> row exists for today AND the local hour is inside a morning window (say 7–11),
> so a late text is still a morning text."

That is not archaeology. It is an actionable work item premised on a mechanism
that does not exist — and `followups.md` is a document minerva's own tooling
re-reads whenever work is scoped:
`minerva:backfill-followups` describes it as write-only, with "every scoping pass
re-reads all of it"; `promote/references/github-issues.md` says it "has to be
re-read in full every time someone scopes work". It is read by `minerva:review`,
`minerva:promote`, and the Phase-1 context assembly of all three
`propose-ship-*` orchestrators — including this run's own.

A `proposal.md` describes what a unit once believed and is evidence. A
`followups.md` is a standing worklist. Same directory, opposite roles.

Two further corrections came out of the replan review:

1. **The correction mechanism was wrong too.** The draft said "correct in place
   with an annotation", borrowing the wiki convention. But
   `backfill-followups/SKILL.md` states the opposite rule for this file type:
   *"Never deletes a `followups.md`. Files are appended to, never rewritten —
   they remain the historical record of what the unit deferred and why."* The
   wiki convention (014's in-place parenthetical) does not transfer here.
2. **The item's mechanism is fully invalidated, not merely mis-premised.** Every
   wiki correction in this unit left a surviving decision — 016's "only
   `run_daily_sync` notifies" is still true. This followup has no substrate at
   all: there is no page-load sync path to hook a catch-up onto. Annotating it as
   though the idea survives would misrepresent it.

## New plan

1. **Append a correction note to `followups.md`; do not rewrite the item.** The
   original bullet stays exactly as written, per the append-only convention. A
   dated note beneath it records that the premise is false, that the option as
   written has no mechanism, and which sibling options remain valid — so the next
   person to scope this file learns it without the record being altered.
2. **Keep `proposal.md` and `scratchpad.archive.md` untouched.** Entry 034's
   archaeology cites `016-daily-balance-digest/proposal.md:22` as the propagation
   origin; rewriting it would destroy the evidence.
3. **Narrow entry 034's Implications bullet** so it states the live-vs-archival
   test rather than a blanket `.minerva/work/*` exemption — the too-broad phrasing
   is what produced this miss, and leaving it would teach the same error.
4. **Propagate the count** (13 → 14 sites, 8 → 9 files) everywhere it appears:
   the proposal's Goal, its Scope heading, entry 034's `**Summary**` and body.
   Also fix a pre-existing drift the review caught — the proposal's Open Questions
   still said "10 sites, 7 files" from an earlier revision.
5. **Restate success criterion 4 as the general test** — no *live* document under
   `.minerva/work/` asserts the claim unannotated — rather than name-checking
   `followups.md`, so a future reader re-derives "live" instead of pattern-matching
   a filename.

## Success criteria — changed

Criterion 1 is unchanged in intent but now explicitly covers live `.minerva/work/`
documents. Criterion 4 is added:

> 4. **No live document under `.minerva/work/` asserts the claim unannotated.**
>    "Live" means the tooling re-reads it when scoping work — `followups.md`,
>    an active `scratchpad.md`, a `replan.md`. Archival ones (`proposal.md`,
>    `scratchpad.archive.md`) deliberately still carry it, as evidence.

The original criteria 4-8 renumber to 5-9.
