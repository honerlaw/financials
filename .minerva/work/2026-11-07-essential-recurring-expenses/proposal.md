# Proposal: essential-recurring-expenses

**Date**: 2026-11-07
**Status**: Shipped (2026-11-07)

**Seed (user's words)**: "Add a mechanism so we can flag a recurring expense as "essential" or not, and then update our total recurring expenses summary header to show the total and then the essential total, this will help us figure out what we should cancel vs keep"

## Goal
On /recurring the user can mark each counted recurring expense **essential** or not with one click.
The "Recurring expenses" headline card shows the total, then the essential subtotal, then the
not-essential remainder (the candidates to cancel).

## Why
The page already answers "what do my recurring bills cost per month". The next question is which of
them to keep. Without a mark, the user has to re-sort the list in their head every visit. A saved mark
and an essential subtotal make the keep/cancel split visible and durable.

## Approach (B — a separate essential-marks table keyed by a stable stream key)
- **Storage.** New table `essential_marks` (`id`, `stream_key` String(255) unique not null,
  `created_at`). Model `EssentialMark` in app/models.py. Alembic revision on top of `a3e6c1d8f205`.
  It is a new empty table with no backfill, verified in isolation per knowledge 017. A mark means
  "essential". No mark means not essential (the default).
- **Stream keys** (pure, computed in `detect_recurring_with_rules`, app/bills.py, for **bills only**;
  income never gets keys or a toggle):
  - A rule-built stream: `{'rule:<id>'}`.
  - A whole-group detected stream: `{'merchant:<k>'}` for each distinct non-empty
    `grouping_key(row)` (app/subscriptions.py; the same function the persisted `merchant_key`
    column holds) among its rows. A group merged by `merge_by_descriptor` (a Plaid rename) carries
    both its old and new keys, so a mark made before the rename still matches after it.
  - A same-amount sub-stream: `{'merchant:<k>@<amount>'}` for **each** distinct non-empty grouping
    key `<k>` among the sub-stream's rows (so a merged group's sub-stream also survives a rename),
    where `<amount>` is `format(split_amount, '.2f')` of the Decimal `split_amount` (e.g. `9.00`). It
    does **not** also carry the parent `merchant:<k>`, so marking one plan at a merchant does not mark
    another.
  - A key longer than 255 characters (`ESSENTIAL_KEY_MAX_LENGTH`, app/bills.py) is left out. A
    stream whose keys are all too long therefore renders no toggle, never one that returns 400.
  - Each bill dict gets `essential_keys` (sorted tuple) and `essential_key`, the key written when
    toggled on: the most common grouping key among its rows, ties to the smallest (or the rule key).
- **Applying marks.** `/recurring` reads the saved keys as plain rows (one constant query; plain rows
  per knowledge 2026-10-26, because the page commits after detection). A bill is essential when any
  of its keys is saved: `bills.mark_essential(bills, saved_keys)` sets `b['essential']`.
  `bills.essential_monthly_total(bills)` returns `(total, count)` over bills that are counted
  (`excluded_reason is None`) **and** essential. It sums the rounded per-row figures, the same way
  `fixed_monthly_total` does.
- **Toggle endpoint.** `POST /recurring/essential` (login required; SameSite=Lax already protects
  POSTs app-wide):
  - fields: `essential` = `1` or `0`, and `key` values. Marking (`1`) takes **exactly one** key,
    which is all the page ever posts. Un-marking (`0`) takes 1 to 500, because a fuzzy-clustered
    group can carry many grouping keys;
  - each key must be at most 255 characters and start with `rule:` or `merchant:`; otherwise 400;
  - `1` inserts the key if it is not already saved. A unique-constraint race is caught and rolled
    back. The rollback also clears an aborted Postgres transaction;
  - `0` deletes every saved mark whose key is among the given keys. The off form posts **all** of the
    stream's keys, so a merged stream is fully unmarked;
  - redirects to `/recurring#counted`.
- **Rule deletion** also deletes that rule's `rule:<id>` mark, so a later rule can never inherit it
  through a reused id.
- **Page.**
  - **Headline card "Recurring expenses":** the total stays as the large figure. Below it go two
    lines: "Essential $Y / month · N of M expenses" and "Not essential $Z / month". Z = total − Y,
    and Z is the candidates to cancel. The existing P75 note stays.
  - **Counted expenses table:** a new "Essential" column. Each row has a small POST form button:
    "Essential" (a new `.btn-success`, which mirrors `.badge-success`; pressing it un-marks) or
    "Mark essential" (ghost; pressing it marks). Both carry `aria-pressed`. The macro lives in
    `app/templates/_essential_toggle.html` so tests can render it directly.
  - The essential split is hidden when no expense is counted, so it never reads "0 of 0".
  - A bill whose `essential_keys` is empty renders **no** toggle. This is defensive only: rows
    with an empty grouping key are in no group, so it should not happen.
  - **Uncounted rows** (annual / transfer / inactive) get no toggle: they are not in the total. A
    mark on a stream that later becomes uncounted is kept and applies again if it is counted again.
  - "Left after recurring" is unchanged.
- **Grants.** Migration `00a2889ed2af` set `ALTER DEFAULT PRIVILEGES` for `financials_admin`, so
  the new table needs no explicit GRANT. `recurring_rules` was added the same way.
- **Unchanged.** Detection, grouping, the index, rules' claiming, the estimates, the income side and
  `fixed_monthly_total`.

### Alternatives considered
- **A — an `essential` column on `RecurringRule`.** Only rule streams could be marked, so marking a
  detected bill would mean writing a rule first. A rule claims rows and changes detection: it forces a
  monthly cadence and is never excluded as a transfer. That is heavyweight, and it mixes "is this
  recurring" with "do I need it". Rejected.
- **C — pattern-based essential tags** (a description substring and optional range that matches
  without claiming rows). This is more robust to grouping changes. But one tag can match several
  streams, unmarking one stream then has to delete a tag that also covers others, and it needs a form
  and a preview. Rejected for a one-click toggle.
- **D — key marks by display name.** This breaks on a Plaid rename, and two merchants that share a
  display name would share a mark (knowledge 032 keeps entity ids apart). Rejected.

### Known consequences
- **Lost marks lean toward "not essential", by design.** A mark lost to any key change moves that
  bill into the "Not essential" remainder, the bucket of candidates to cancel. The row then shows
  "Mark essential" again in the counted table, so the user sees it while reviewing the list, and
  nothing is cancelled automatically. A count of saved marks that match nothing was considered and
  left out, because it cannot say which bill lost its mark.
- **A whole-group stream can turn into split sub-streams.** For example, one off-price charge can
  make the whole group fail detection. Its sub-streams carry only `@<amount>` keys and start
  unmarked.
- **Merges can pass a mark on.** When `merge_by_descriptor` joins a marked group with another, the
  merged stream is essential, and un-marking it deletes both keys. If the merge later stops applying,
  only the half whose key was saved stays marked.
- **A stale un-mark form can leave a mark.** If a page loaded before a rename or re-merge posts
  only part of the stream's current keys, a leftover key keeps the stream essential. The page
  re-renders showing it still marked, and a second click clears it.
- **An old key can come back.** If Plaid ever gives a retired entity id or normalized name to a
  different merchant, a stale mark would match it. This is the same accepted class as orphaned marks.
- **`rule:<id>` is stable.** There is no rule edit route, and Postgres does not reuse ids. Deleting
  a rule deletes its mark anyway.
- If Plaid re-enriches **every** row of a stream to a new entity id or name, or a normalizer version
  change alters `grouping_key`, the stream's keys change and it shows unmarked again. This is visible,
  and the user re-marks it. The orphaned mark stays in the table, harmless, with no cleanup UI.
- A same-amount sub-stream whose price changes is a new sub-stream and starts unmarked.
- Taking a detected stream over with a rule changes its key to `rule:<id>`. The mark does not carry
  over, so the user re-marks it.

## Success criteria
1. Pure tests (fictional fixtures, fixed dates per knowledge 004) cover the key sets of:
   - a whole-group stream (`merchant:<k>`);
   - a merged (renamed) group, which carries both keys;
   - a same-amount sub-stream (the `@<amount>` suffix);
   - a rule stream (`rule:<id>`);
   - an income stream, which has no keys;
   - two same-amount sub-streams of one merchant: marking one leaves the other unmarked;
   - a sub-stream of a merged (two-key) group carries an `@<amount>` key for each grouping key.
2. `mark_essential` and `essential_monthly_total`: only counted, essential bills are summed. The
   total equals the sum of those rows' displayed `monthly_amount`. A mark on an uncounted bill adds
   nothing.
3. Route tests:
   - POST `essential=1` creates the mark, and /recurring then shows the row as Essential and the
     essential subtotal in the header;
   - POST `essential=0` with all keys removes the marks;
   - a malformed key, a key over 255 characters, no key, or more than 500 keys returns 400;
   - on the page, marking one same-amount sub-stream shows only that row as Essential;
   - a bill with empty `essential_keys`, rendered through the recurring template, gets no toggle
     form;
   - the endpoint requires login;
   - for a merged (two-key) stream, marking it and then posting the off form shows it unmarked;
   - a rule-built stream can be toggled on and off;
   - with no marks, the header shows Essential $0.00 and Not essential equal to the total. In every
     header test, essential + not essential == the total.
4. Deleting a rule deletes its `rule:<id>` mark.
5. The existing query-count guards (`test_page_query_count_does_not_grow_with_transactions`,
   `test_page_query_count_does_not_grow_with_rules`) still pass, and marks add a constant number of
   queries.
6. The new migration is verified in isolation per knowledge 017: upgrade creates the table and the
   unique constraint, and downgrade drops it.
7. `uv run pytest` passes in full. Every fixture is fictional, because the repo is public.

## Open Questions
None blocking. Binary essential / not essential, defaulting to not essential, is the plain reading of
the seed.
