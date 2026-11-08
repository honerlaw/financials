# Proposal: quick-not-recurring

**Date**: 2026-11-08
**Status**: Shipped (2026-11-08)

## Goal
The user can mark a stream on /recurring as not recurring (including a subscription they cancelled) with one click on that row, without leaving the page. They can undo it with one click too.

## Why
The user said: "make it easier to mark something as 'not recurring or cancelled or something' on the recurring page… right now I have to navigate to a new page and save a rule". Today every row's **Flag** link opens `/recurring/rules/new`. There the user picks "not recurring", reads the preview and presses Save. The possibly-recurring list's "Not recurring" link opens the same form. Undoing means finding the rule on the "Your rules" card and pressing Delete.

The form's preview exists because a rule's pattern can reach past the row it started from. That happens with a check group, a transfer pattern, or an unranged pattern beside a same-amount plan (knowledge 2026-11-07-decision-user-rules-correct-recurring-detection). For most rows the pattern hint claims exactly the row's own transactions, so the preview is a confirmation step that adds nothing.

## Approach (as built: one-click POST of a stream locator; the server saves only when the rule claims exactly that stream)
- **Route `POST /recurring/rules/quick`** (`login_required`). The button posts only a **locator**:
  - `stream_key` (repeated): the stream's `stream_keys`;
  - `direction`;
  - `split_amount`, for a same-amount plan only.

  The field is `stream_key` because the essential toggle's forms already post `key`. Label and pattern are not posted.
  - The route loads the saved rules (`_rule_rows()`) and groups (`groups_for_detection()`), and runs `detect_recurring_with_rules(groups, today, rules)`.
  - `locate_stream(found, keys, split_amount, direction)` (`app/recurring_rules.py`) returns the single non-rule bill, income stream or suggestion whose `stream_keys`, `split_amount` (as `Decimal`) and side match.
  - The candidate is built from the located stream's `name` and `pattern_hint`, ranged to `split_amount` when there is one, with `action='not_recurring'`. It is validated by `parse_rule_form`, and `preview` runs over the **same `groups` object**. The route commits after both, in the same order as `/recurring`.
  - `quick_mark_verdict(stream, preview_result, direction)` is true only when the set of rows the candidate would win, by object identity, equals the stream's rows on that side; that set is not empty; and `taken` is empty. Then the rule is saved, and the route redirects to `/recurring?marked=<id>#marked-notice`.
  - When it is not true, or the hint fails validation (for example, under 3 characters), the route redirects to `GET /recurring/rules/new` with the label, pattern, direction, amounts, `action=not_recurring` and `preview=1`.
  - **No stream located:** if a saved `not_recurring` rule's claim has the same `stream_keys` and direction and exactly the posted range, the route redirects to that rule's `?marked` (a double click, or a page from before the mark). Otherwise it redirects to /recurring. Malformed input also redirects to /recurring with nothing saved: no key, more than 500 keys, a bad direction, or an unparseable or non-finite amount.
- **Support code.** `detect_recurring_with_rules` gives each non-rule stream and suggestion `rows` (references to the rows it was built from) and `stream_keys` (sorted distinct grouping keys of those rows). Rule streams get `stream_keys = ()`. Each `_rule_entry` carries its claim's `stream_keys`. `preview` returns `won_rows`.
- **Why identity holds.** `apply_rules` partitions by reference. `merge_by_descriptor` copies lists, not rows. Sub-streams and suggestions are slices by reference. A merged stream therefore carries both index groups' keys and rows.
- **UI** (`recurring.html`):
  - A `quick_mark` macro renders an inline **Not recurring** button (`.inline-form`, `btn btn-sm btn-ghost`). Its title reads: "Stop counting this: not a bill, or one you cancelled. Future charges matching it stay hidden too…".
  - The button appears next to the Flag link on every non-rule row with keys (counted, not counted and income), with same-amount plans posting their amount.
  - It replaces the suggestions' old "Not recurring" link. `has_split` suggestions stay withheld. Rule rows get no button.
  - **Notice** (`id="marked-notice"`): `?marked` is read with `type=int` and matched against the already-loaded `found.rules`, `not_recurring` only. It shows the label, row count, the pattern still hidden, the sources and an **Undo** (delete).
  - Each **Marked not recurring** row gets an **Undo**. That disclosure renders `open` while a notice shows. The Not-counted heading gets `id="not-counted"`.
- **Unchanged:** the rule model and migration, precedence, detection results, the form and the delete route.

### Alternatives considered
- **B: one-click save with no containment guard**, relying on the notice and Undo to show what was claimed. Simpler, but one click on a check stream or a broad transfer hint would silently claim unrelated rows across groups. That is exactly the risk the form's preview exists for.
- **C: a per-stream "dismiss" flag keyed by stream key (a new table, like essential marks).** This was rejected in the rules work (knowledge 2026-11-07, alternative B), because it duplicates the not-recurring mechanism. Keys are also lost when Plaid re-enriches rows, so a cancelled subscription would silently reappear.
- **D: an inline expanding preview per row** (details or a fetch) with a confirm button. It keeps the preview but costs one `apply_rules` pass per row on page load, or new JavaScript. It is still two clicks, and A already gives the preview exactly when it matters.

## Success criteria
1. **Unit** (`tests/test_quick_not_recurring.py`, fictional fixtures):
   - `preview` returns the candidate's `won_rows`.
   - `quick_mark_verdict` is true when the hint claims exactly the stream's rows. It is false when:
     - a row of another group is also won;
     - only some of the stream's rows are won (a hint that falls back to one description);
     - rows are taken from a saved rule;
     - `locate_stream` returns None for keys, side or amount that do not match.
2. **Detection:** each whole-group bill, income stream, same-amount sub-stream and suggestion carries `rows` and `stream_keys` (its rows' distinct grouping keys). A rule stream carries `stream_keys` of `()`.
3. **Routes** (`tests/test_quick_not_recurring.py`, frozen clock, fictional data):
   - Quick-marking a counted bill saves one `not_recurring` rule and redirects to `/recurring?marked=<id>#marked-notice`. The page then no longer counts the bill, lists it under Marked not recurring, and shows the notice (with the pattern) and Undo.
   - Quick-marking an income stream saves an inflow rule.
   - Quick-marking a same-amount sub-stream saves a rule ranged to exactly that amount, and the sibling plan stays counted.
   - Quick-marking a stream merged from two index groups (`merge_by_descriptor`) saves and claims both groups' rows.
   - A pattern that would also claim another group's rows saves nothing. A pattern that would claim only part of the stream saves nothing. Both redirect to the form with `action=not_recurring` and `preview=1`, and the form renders the preview.
   - Posting the same quick mark twice saves one rule. The second post redirects to `?marked=<first id>`.
   - A stream whose own hint is under 3 characters saves nothing and opens the form. Malformed input saves nothing and redirects to /recurring: no key, over 500 keys, a bad direction, an unparseable or non-finite amount, or unknown keys.
   - Reposting a marked plan (even as `9.0`) confirms its own rule.
   - The route redirects to /login when logged out.
   - Every non-rule row with a Flag link renders a Not recurring button. Rule-built rows and `has_split` suggestions do not.
   - Each Marked-not-recurring row has an Undo button that deletes its rule.
   - Quick-marking an essential-marked bill and then undoing it leaves the bill essential, because the `merchant:` mark is untouched.
   - A same-amount plan with a non-round amount (for example 12.34) saves directly.
   - `?marked=<unknown id>` and `?marked=abc` render no notice and no error.
4. The /recurring query-count tests (`test_page_query_count_does_not_grow_with_rules`, `..._with_marks`, `..._with_transactions`) still pass.
5. `uv run pytest` passes.

## Open Questions
- A not-recurring rule from a hint also hides future charges matching the pattern. That is right for a cancelled subscription. If the user re-subscribes, the new charges stay hidden until Undo. The notice and the Marked list keep the rule visible.
- Quick-marking one same-amount plan turns the sibling plan into the merchant's whole-group stream. Its essential key loses the `@amount` suffix, so a saved essential mark on it stops matching. Undo restores it. This is recorded in the knowledge entry rather than changed.
