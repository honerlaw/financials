# Only the call site is authoritative for runtime behaviour — corroborating docs are one source, not two

**Date**: 2026-08-24
**Type**: pattern
**Summary**: A claim that `/api/sync` fired on every dashboard page load lived at fourteen sites across nine files — code, tests and the knowledge wiki — and was never true in any revision; it spread because each new author read it from the previous document rather than the call site, so the usual "check a second source" mitigation confirmed it instead of catching it.
**Context**: .minerva/work/2026-08-24-page-load-sync-correction

## The claim, and the archaeology

Fourteen places in this repo stated that `POST /api/sync` runs on every dashboard
page load. `/api/sync` is POST-only and has exactly one caller: `triggerSync(btn)`
in `app/templates/base.html`, behind a button's `onclick`.

It is not a comment that went stale when behaviour changed. `git show
7043b4e:app/templates/base.html` — the commit that first added the templates —
already has the fetch inside `triggerSync`. There is no revision of `base.html`
or `index.html` in which a page-load sync existed. **The documentation never
described reality.**

That distinction is worth the archaeology it takes to establish. "The behaviour
changed and a comment was missed" implies a maintenance lapse and suggests
looking for what removed the auto-sync. "It was never true" points somewhere
else entirely: at how the belief got written down in the first place, and at
every other document that repeated it.

## How it spread

Fourteen sites across nine files, none of them verified once. Five in code and
tests:

- `app/sync.py`, `run_daily_sync` docstring — the claim, plus a contrast drawn
  against "whenever the dashboard is next opened", an alternative that never
  existed
- `app/sync.py`, `_create_account_if_missing` docstring
- `app/notifications.py`, module docstring
- `tests/test_sync.py` — in the *name* of a test function,
  `test_page_load_sync_does_not_text`, and its docstring
- `tests/test_sync.py` again, in `test_create_account_if_missing_survives_a_concurrent_insert`

And eight in the wiki:

- [[010-decision-budget-alert-notifier]], Decision 1
- [[016-decision-daily-digest-notifier]] — `**Summary**`, `## Context`, and
  Decision 2
- [[023-bug-transactions-sync-is-not-the-only-account-source]], the write-race
  bullet
- `overview.md`, twice
- `index.md`, in the catalog line mirroring 016's Summary

And one in a live work-unit record:

- `016-daily-balance-digest/followups.md`, proposing deferred work built on the
  path that does not exist

Each author had a plausible source: the previous document. The chain is still on
disk. `.minerva/work/016-daily-balance-digest/proposal.md:22` states it as
settled fact — *"the 7am cron, or any of the background syncs `/api/sync` fires
on every dashboard page load"* — and that proposal is what `minerva:promote`
turned into knowledge entry 016, which `minerva:synthesize` then summarised into
`overview.md`, which the next unit read. Unit 021's proposal and unit 012's
repeat it independently, each having read an earlier document rather than the
code. Nothing anywhere in that chain touches `app/routes.py` or `base.html`.

Note where the amplification happens: a claim in a work-unit proposal is one
unit's working assumption, and wrong assumptions there are ordinary and cheap.
**Promote is the step that converts it into something every future agent reads as
settled.** That is the point in the lifecycle where a sentence about runtime
behaviour is worth ten seconds of grep.

## Why the standard mitigation failed

The usual defence against trusting a comment is to check a second source. Here
that makes it worse. A reader who doubted `sync.py`'s docstring and consulted
`.minerva/knowledge/` found 016 agreeing with it, and `overview.md` agreeing
again. Three independent-looking confirmations, one unverified origin.

This is not hypothetical: a session working in this repo on 2026-08-24 relied on
it to warn a parallel session that background syncs would run during page
renders, and cited the docstring. The parallel session checked the call site and
found nothing. `CLAUDE.md` directs every agent to read `.minerva/knowledge/`
before starting work here, which is exactly what gives a false entry its reach.

## The rule

**For a claim about what calls what, or when something runs, the call site is the
only authoritative source.** A docstring, a knowledge entry, and an overview
narrative that all agree are one source three times over, because in a wiki built
by promotion they usually descend from each other. Corroboration across documents
is evidence about the corpus, not about the code.

Cheap in practice — the check is one grep:

```bash
grep -rn "api/sync" app/templates/ app/static/ app/routes.py
```

Two further habits this incident argues for:

- **When a document asserts runtime behaviour, verify before repeating it**,
  particularly when promoting a proposal's prose into a knowledge entry. Promote
  is where an unverified sentence stops being one unit's working note and becomes
  something every future agent reads as settled.
- **When correcting such a claim, grep for every form of it before declaring
  done — do not work from a list.** This one was inventoried at three sites, then
  ten, then thirteen, then fourteen. Four counts, four undercounts: two
  independent reviewers each found sites the previous pass had missed, a
  mechanical repo-wide sweep found one both had missed, and a completion check
  found a fourteenth that the sweep's own exclusion rule had wrongly filtered
  out — the sweep was correct, its exclusion was not. A partial correction is worse than
  none, because it leaves the surviving copies looking freshly confirmed.

## Implications

- Corrections here were made **in place and annotated**, following
  [[014-decision-plaid-liabilities-piggyback-on-sync]]'s convention — the entries
  say what they originally claimed and that it was wrong, rather than being
  quietly rewritten. The record that the corpus was confidently wrong about its
  own runtime is the most useful part of it.
- No decision changed. 016's "only `run_daily_sync` notifies" and 010's "fires
  from the sync path, every sync" were correct throughout; only their stated
  premises were false. The concurrency race in
  [[023-bug-transactions-sync-is-not-the-only-account-source]] is likewise real —
  overlapping syncs come from the 7am job, the reconnect trigger, and repeated
  button presses.
- **Correcting a record depends on whether it is live or archival — not on which
  directory it sits in.** That distinction is easy to get wrong: this unit first
  exempted all of `.minerva/work/` as historical and missed a live site inside it.
  `proposal.md` and `scratchpad.archive.md` describe what a unit once believed and
  are evidence, so they were deliberately left carrying the claim. `followups.md`
  is a standing worklist that `minerva:review`, `minerva:promote` and every
  `propose-ship-*` orchestrator re-read when scoping work — a false premise there
  is a live instruction, not archaeology. `016-daily-balance-digest/followups.md`
  proposed building "a bounded catch-up on the page-load sync path", work with no
  substrate at all.
  Its correction was **appended, not written in place**: `backfill-followups`
  specifies that `followups.md` files are "appended to, never rewritten". The
  in-place annotation convention that applies to wiki entries does not transfer
  to every record.
- `index.md`'s catalog lines do **not** regenerate from an entry's `**Summary**`.
  `knowledge_fix.py::plan_index` preserves each surviving line verbatim and only
  adds lines for entries that lack one, and no lint check compares the two. A
  corrected Summary therefore leaves a stale catalog line that reconciliation
  will never notice — it has to be hand-edited in the same change.

## Related

- [[016-decision-daily-digest-notifier]] — corrects the premise stated in its Summary, Context and Decision 2; its decision is unchanged.
- [[010-decision-budget-alert-notifier]] — corrects the same premise in its Decision 1.
- [[023-bug-transactions-sync-is-not-the-only-account-source]] — corrects the trigger named in its write-race bullet; the race itself is real.
- [[014-decision-plaid-liabilities-piggyback-on-sync]] — the in-place annotation convention followed here for a factual error in a past entry.
- [[020-pattern-injected-fakes-hide-construction-failures]] — see also, another case where the thing that made verification convenient is what prevented it.
- [[028-pattern-byte-assertions-are-contracts-or-snapshots]] — see also, on classifying what a record actually guarantees before trusting it.
