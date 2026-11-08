# A one-click "Not recurring" saves its rule only when the rule claims exactly the clicked stream

**Date**: 2026-11-08
**Type**: decision
**Theme**: recurring-detection
**Summary**: Quick mark posts a stream locator; server rebuilds the rule, saving only on exact row-set equality.
**Context**: .minerva/work/2026-11-08-quick-not-recurring (see git history if the worktree has been cleaned up)

## Context

Marking a /recurring row "not recurring" used to mean opening the rule form, choosing the action
and saving. The form's preview exists because a rule's pattern hint can reach past the row it came
from. It can claim rows of other groups or of a sibling same-amount plan. Or, when the hint falls
back to one description, it can match only part of the stream and leave the rest counted.

## Finding

1. **The button posts only a locator.** `POST /recurring/rules/quick` takes these form fields:
   - `stream_key` (repeated): the stream's `stream_keys`, the sorted distinct grouping keys of its rows;
   - `direction`;
   - `split_amount`, for a same-amount plan only.

   The field is `stream_key`, not `key`, because the essential toggle's forms already post `key`.
2. **The server rebuilds everything.** The route reads groups with `groups_for_detection()` and
   runs `detect_recurring_with_rules` over the saved rules. It locates the one non-rule stream or
   suggestion with those keys, that `split_amount` and that side (`locate_stream`). It builds the
   candidate from the stream's own `name` and `pattern_hint`, ranged to the plan's amount, and runs
   `preview` over the **same group lists**.
3. **It saves only on exact equality, by row identity.** The rows the candidate would win must equal
   the stream's rows on the rule's side, with at least one row and none taken from a saved rule
   (`quick_mark_verdict`). This works because nothing in detection copies rows:
   - `apply_rules` partitions rows by reference;
   - `merge_by_descriptor` copies lists but not rows;
   - every stream and suggestion carries `rows`, holding references.

   A merged stream carries both index groups' keys, and its rows are both groups' rows.
4. **Each other outcome has its own landing page:**
   - not equal, or a hint that fails validation → the rule form, with `action=not_recurring&preview=1`;
   - no stream located, but a saved not-recurring rule whose claim has these keys, direction and
     exact range (a double click or a stale page) → that rule's confirmation;
   - malformed or unknown input → /recurring, with nothing saved.
5. **Confirm and undo on the page.** The route redirects to `/recurring?marked=<id>#marked-notice`.
   The page reads `marked` with `type=int` and finds the rule in the already-loaded `found.rules`,
   so it costs no query. It shows the rule's label, row count, pattern and sources with an Undo.
   Every "Marked not recurring" row also has Undo, which posts to the existing delete route.

## Implications

- **A quick mark hides future matches too.** It is an ordinary unranged `not_recurring` rule, ranged
  only for a same-amount plan. A re-subscribed or renewed charge with the same descriptor stays
  hidden until Undo. The notice and the button's title say so.
- **Marking one plan can drop its sibling's essential mark.** Once one same-amount plan is claimed,
  the sibling's rows are the whole group. It renders as the merchant's own stream, and its essential
  key changes from `merchant:<k>@<amount>` to `merchant:<k>`. This adds "split becomes whole" to
  the ways a mark is lost. Undo restores it.
- **The cost lands on the click, not the page.** One detection pass and one preview per POST.
  /recurring itself adds no query.
- **A future quick action should reuse the locator and row-equality pattern**, not trust posted
  rule fields.

## Related
- [[2026-11-07-decision-user-rules-correct-recurring-detection]] — the rule mechanism and the preview this bypasses only when it would add nothing
- [[2026-11-07-decision-essential-marks-keyed-by-stream]] — key scheme behind the sibling-plan mark loss
- [[2026-11-07-decision-split-undetected-groups-by-exact-amount]] — why a plan's quick rule is ranged to its exact amount
- [[2026-11-07-decision-merge-groups-renamed-by-plaid]] — merged streams carry several keys and both groups' rows
- [[2026-10-26-bug-commit-before-detection-reloaded-every-transaction]] — the route commits only after detection and preview
