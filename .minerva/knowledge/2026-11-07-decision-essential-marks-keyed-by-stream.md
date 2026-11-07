# Recurring expenses are marked essential by stream key, and /recurring splits the total into essential and not

**Date**: 2026-11-07
**Type**: decision
**Theme**: recurring-detection
**Summary**: `essential_marks` stores stream keys (`rule:<id>`, `merchant:<grouping key>[@amount]`); a bill matching any saved key is essential.
**Context**: .minerva/work/2026-11-07-essential-recurring-expenses (see git history if the worktree has been cleaned up)

## Context

The user wanted to know which recurring expenses to keep and which to cancel. /recurring showed one
total. Streams are recomputed per request and have no stored identity. A stream is a merchant group
(possibly merged across a Plaid rename), a same-amount sub-stream, or a rule-built stream, so a mark
needed a key that survives recomputation.

## Finding

1. **Keys, set in `detect_recurring_with_rules` (app/bills.py)**, for bills only. Income gets `()`.
   - A rule stream gets `rule:<id>`.
   - A whole-group stream gets `merchant:<k>` for each distinct non-empty `grouping_key(row)`.
   - A same-amount sub-stream gets `merchant:<k>@<amount:.2f>` for each of its rows' grouping keys,
     and **not** the parent key. Marking one plan therefore never marks a sibling.
   - Every stream dict carries `essential_keys` (a sorted tuple), `essential_key` (the key saved when
     marking: the most common grouping key, ties to the smallest) and `essential`.
   - A key over String(255) is left out, so a stream whose keys are all too long renders no toggle
     rather than one that returns 400.
2. **Matching is any-key.** `mark_essential(streams, saved)` sets `essential` when any key is saved.
   A group merged across a rename carries both names' keys, so a mark made under either still matches.
3. **Totals.** `essential_monthly_total` is `fixed_monthly_total` over the essential bills: counted
   only, summing the rounded rows. The headline card shows the total, "Essential $Y · N of M" and
   "Not essential $(total − Y) · could be cancelled". The split is hidden when no expense is counted.
4. **Toggle.** `POST /recurring/essential` redirects to `/recurring#counted`.
   - `essential=1` takes **exactly one** key and inserts it if absent. A unique-constraint race is
     caught and rolled back.
   - `essential=0` deletes every saved key it is given, up to 500. The off form posts all of the
     stream's keys.
   - A key must start with `rule:` or `merchant:` and be at most 255 characters.
   - Deleting a rule also deletes its `rule:<id>` mark.
5. **One plain query.** The page reads the marks as a scalar column before detection, so the commit
   after detection has nothing to expire (knowledge 2026-10-26). Detection, grouping, the index and
   the rules are unchanged.
6. **Template.** The toggle macro lives in `app/templates/_essential_toggle.html`.
   `get_template_attribute('recurring.html', …)` evaluates the whole page module and fails on
   undefined page variables, so a macro that tests call directly must live in a partial.
7. **Migration `b8d4e2f7a9c1`.** It adds one table and needs no GRANT, because `00a2889ed2af` set
   default privileges. It was verified in isolation per knowledge 017.

## Implications

- **A lost mark leans toward "not essential", the cancel bucket.** Marks are lost when:
  - Plaid re-enriches every row of a stream;
  - a normalizer change alters `grouping_key`;
  - a whole-group stream becomes split sub-streams;
  - a price change creates a new sub-stream;
  - a rule takes a detected stream over (its key becomes `rule:<id>`).

  The row then shows "Mark essential" again. The orphaned key stays in the table, harmless, and no
  cleanup UI exists.
- **A merge passes a mark on.** If `merge_by_descriptor` joins a marked group with another, the
  merged stream is essential. If the merge later stops applying, only the half whose key was saved
  stays marked.
- **Marking is advisory only.** It never changes what is counted, detected or claimed.

## Related
- [[2026-11-07-decision-user-rules-correct-recurring-detection]] — rule streams are keyed `rule:<id>`; deleting a rule deletes its mark
- [[2026-11-07-decision-merge-groups-renamed-by-plaid]] — why a merged stream carries several keys and any one matches
- [[2026-11-07-decision-split-undetected-groups-by-exact-amount]] — sub-streams get `@amount` keys without the parent key
- [[2026-11-06-decision-recurring-page-and-income-rule]] — the headline card this splits; income is never marked
- [[2026-10-26-bug-commit-before-detection-reloaded-every-transaction]] — marks are read as plain values
- [[017-pattern-migration-chain-is-postgres-only]] — how `b8d4e2f7a9c1` was verified
- [[032-constraint-plaid-entity-ids-must-never-fuzzy-merge]] — why display names were rejected as keys
