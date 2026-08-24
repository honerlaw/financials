# Proposal: page-load-sync-correction

**Date**: 2026-08-24
**Status**: Draft (replanned 2026-08-24 — see replan.md)
**Closes**: #44

## Goal

Correct the claim that `POST /api/sync` fires on every dashboard page load —
which was never true — everywhere it appears: fourteen sites across nine files,
in code, tests, the knowledge wiki and one live work-unit record. Corrections in the wiki are annotated rather than silently
rewritten, following the convention entry 014 already set.

## Why

Three code files, two of them tests, and four wiki files assert that `/api/sync`
runs on every dashboard page load. It does not. `/api/sync` is POST-only and has exactly
one caller: `triggerSync(btn)`, wired to a button's `onclick` in
`app/templates/base.html`.

**It was never true.** Commit `7043b4e` — the first commit to add the templates —
already had the fetch inside `triggerSync`, behind that button. No revision of
`base.html` or `index.html` has ever auto-fired it. This is not a comment that
went stale when behaviour changed; it describes behaviour that never existed.

Why that matters more than an ordinary stale comment: `CLAUDE.md` directs every
agent to read `.minerva/knowledge/` before working in this repo, so a false claim
there is load-bearing input to design decisions. It already misled a concurrent
session today into warning that background syncs would run during page renders.
That session noted the sharpest part: the usual mitigation — don't trust a
comment, check a second source — would have *confirmed* the error here, because
the docstring and the wiki corroborate each other. A corpus that agrees with
itself is not independent evidence.

## Approach

**Annotate in place; do not silently rewrite.** Entry
`014-decision-plaid-liabilities-piggyback-on-sync` already handles a factual
error in its own body this way — it names what the entry originally said, states
that it was wrong, notes what the miss cost, and links to the correcting entry.
That is the settled convention here, so this change follows it rather than
inventing one. Code comments get no such treatment: they are not historical
records, so they are simply corrected.

**Rejected alternatives:**

- **Silently rewriting the false sentences.** Cheapest, cleanest prose, and it
  destroys the most useful part of the record — the evidence that the corpus was
  confidently wrong about its own runtime for months.
- **Leaving the wiki alone and writing only a new correcting entry.** This is how
  `001` was handled when `023` corrected it, but `001` never contained a
  standalone misleading sentence. Here the false claim sits in 016's `**Summary**`
  — the text `index.md` shows — and in `overview.md`, the wiki's front door. A
  reader hits the falsehood first and may never reach the correction.
- **A supersession banner** (`<!-- superseded-by: NN -->` plus a blockquote, as
  live on `010`). Rejected deliberately, not overlooked: 016's *decision* is
  entirely intact — only `run_daily_sync` notifies, and `sync_all_institutions()`
  is silent. Only its stated premise is false. A banner would falsely announce
  that the decision itself had been retired.

### Two mechanical traps this must not fall into

1. **`index.md`'s catalog line will not self-heal.** The catalog line for 016 is
   byte-identical to its `**Summary**` and carries the false claim. But
   `knowledge_fix.py::plan_index` "preserves each surviving catalog line
   verbatim" and only *adds* a line for an entry that lacks one — it never
   regenerates an existing line from the entry's current `**Summary**`. No
   `knowledge_lint.py` check compares catalog text against Summary text either.
   So editing the Summary alone leaves `index.md` asserting the falsehood
   permanently, and neither `minerva:cleanup` nor lint would ever surface it.
   **The catalog line must be hand-edited in this change.**
2. **`## Related` labels must avoid the words "supersede" and "contradict".**
   `knowledge_fix.py` treats those as `DIRECTIONAL_TERMS`; a prose label
   containing either substring without being the exact term causes the reciprocal
   back-link to be refused, leaving a warning nothing auto-repairs.

### Scope — 14 sites across 9 files

**Code and tests** (corrected outright):
- `app/sync.py`, `run_daily_sync` docstring — two false clauses: the page-load
  claim, and "lands at a predictable hour instead of whenever the dashboard is
  next opened", a contrast drawn against an alternative that never existed.
- `app/sync.py`, `_create_account_if_missing` docstring — "spawns an
  unsynchronized thread on every dashboard load". The overlap race it motivates
  is **real** (7am job, reconnect trigger, repeated button presses); only the
  trigger is wrong. The safety rationale must survive intact.
- `app/notifications.py:35` — "not from the per-page-load sync".
- `tests/test_sync.py:489` — the function *name* `test_page_load_sync_does_not_text`
  plus its docstring, which restates both false clauses. The assertion itself is
  correct and unchanged; only the name and prose are wrong.
- `tests/test_sync.py:939` — `test_create_account_if_missing_survives_a_concurrent_insert`'s
  docstring mirrors `_create_account_if_missing`'s. Found by the criterion-1 grep
  after both scope reviews had closed; see the note under Success criteria.

**Knowledge** (annotated in place):
- `016-decision-daily-digest-notifier.md` — three occurrences: `**Summary**`,
  `## Context`, and Decision 2.
- `010-decision-budget-alert-notifier.md` — Decision 1.
- `023-bug-transactions-sync-is-not-the-only-account-source.md` — the write-race
  bullet. Same rule as `_create_account_if_missing`: the race is real, the
  trigger description is not.
- `overview.md` — two occurrences.
- `index.md` — 016's catalog line (hand-edited; see trap 1).

**Live work-unit records** (corrected by appending, not rewriting):
- `.minerva/work/016-daily-balance-digest/followups.md` — proposes "a bounded
  catch-up on the page-load sync path", deferred work with no substrate. A dated
  correction note is appended beneath the original, which stays exactly as
  written: `backfill-followups` specifies `followups.md` files are "appended to,
  never rewritten". Added after the completion gate; see `replan.md`.

**Left uncorrected on purpose:** the *archival* records — `proposal.md` files and
`scratchpad.archive.md` — that carry the claim, including
`016-daily-balance-digest/proposal.md:22`, where it entered the wiki. They record
what a unit believed at the time, which is what makes them the evidence for the
propagation chain; rewriting them would erase it. The distinction is live vs
archival, **not** which directory the file sits in — drawing it by directory is
what caused the 14th site to be missed.

**Explicitly out of scope:** a corpus-wide audit for *other* unverified runtime
claims. Offered to the user at intake and declined. This unit completes the
inventory of one specific, confirmed-false claim; it does not go looking for
siblings.

**Deliberately left alone:** `app/notifications.py:396` and `018:45` both say the
lazy `twilio` import "stays lazy on a page load". That is about import behaviour
while rendering the dashboard, which genuinely happens, and is unrelated to any
sync firing. Both statements survive the correction and must not be swept up.

## Success criteria

1. **No unannotated occurrence survives.** A repo-wide grep for the claim's forms
   ("page load", "page-load", "page_load", "dashboard load", "dashboard is next
   opened") returns only corrected text, annotations describing the former error,
   and the two `twilio`-laziness statements named above.
2. **`index.md`'s catalog line for 016 matches 016's corrected `**Summary**`.**
   Verified by direct comparison, not by assuming reconciliation will fix it.
3. **Every corrected decision survives.** 016's "only `run_daily_sync` notifies"
   and 010's "fires from the sync path, every sync" are unchanged; only their
   premises are corrected. The concurrency rationale in
   `_create_account_if_missing` and in 023 still motivates its savepoint.
4. **No live document under `.minerva/work/` asserts the claim unannotated.**
   "Live" means the tooling re-reads it when scoping work — `followups.md`, an
   active `scratchpad.md`, a `replan.md`. Archival records (`proposal.md`,
   `scratchpad.archive.md`) deliberately still carry it, as evidence.
5. **`app/sync.py` and `app/notifications.py` diffs are docstring/comment only** —
   no executable line changes in either.
6. **The test still passes and still asserts the same thing.** Only its name and
   docstring change; `sync_all_institutions()` must still be shown not to notify.
7. **Full suite green.**
8. **A new `Type: pattern` knowledge entry** records the archaeology (`7043b4e`)
   and the generalizable failure mode: the only authoritative source for runtime
   behaviour is the call site, and mutually-corroborating documentation is one
   source, not two.
9. **`knowledge_lint.py` reports 0 errors**, with any warnings limited to
   `pending reconciliation` — the expected state on a work-unit branch, since
   promote is add-only and `minerva:cleanup` writes the reciprocals and catalog
   lines on the default branch. Every new `## Related` label is free of the
   `DIRECTIONAL_TERMS` substrings, so none of those reciprocals will be refused.

## Open Questions

None blocking. The user adopted #44 as the unit's goal at intake and declined the
broader corpus audit.

One thing the user should know rather than discover in the diff: the option they
approved was previewed as "3 files, prose only, no executable line changes". Both
scope gates found the inventory materially larger, and the acceptance sweep and
the completion gate each grew it again — 14 sites across 9 files, against the 3
the issue named — and renaming a test function is an executable line change. The
direction is unchanged; the extent grew because every site left asserting the
false claim reproduces the exact failure #44 exists to prevent.
