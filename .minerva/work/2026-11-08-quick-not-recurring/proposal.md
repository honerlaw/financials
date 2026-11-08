# Proposal: quick-not-recurring

**Date**: 2026-11-08
**Status**: Draft

## Goal
The user can mark a stream on /recurring as not recurring (including a subscription they cancelled) with one click on that row, without leaving the page. They can undo it with one click too.

## Why
The user said: "make it easier to mark something as 'not recurring or cancelled or something' on the recurring page… right now I have to navigate to a new page and save a rule". Today every row's **Flag** link opens `/recurring/rules/new`. There the user picks "not recurring", reads the preview and presses Save. The possibly-recurring list's "Not recurring" link opens the same form. Undoing means finding the rule on the "Your rules" card and pressing Delete.

The form's preview exists because a rule's pattern can reach past the row it started from. That happens with a check group, a transfer pattern, or an unranged pattern beside a same-amount plan (knowledge 2026-11-07-decision-user-rules-correct-recurring-detection). For most rows the pattern hint claims exactly the row's own transactions, so the preview is a confirmation step that adds nothing.

## Approach (A: one-click POST that saves when the rule claims exactly the clicked stream, and falls back to the form when it does not)
- **Route `POST /recurring/rules/quick`** (`login_required`). It takes `label`, `pattern`, `direction`, optional `amount_min`/`amount_max`, and a **stream locator**: one or more `key` (the stream's `stream_keys`), plus `split_amount` (empty unless the stream is a same-amount plan).
  - It builds a candidate with `parse_rule_form` and `action='not_recurring'`.
  - It loads groups with `groups_for_detection()` and the saved rules with `_rule_rows()`, the way `/recurring` does. It then runs `detect_recurring_with_rules(groups, today, saved)` to recompute the page's streams, and `preview(groups, saved, candidate)` over the **same `groups` object**. It commits after both, in the same order as `_render_rule_form`.
  - **Locate the stream.** Find the non-rule bills, income or suggestions whose `stream_keys` equal the posted keys, whose `split_amount` equals the posted one (both parsed as `Decimal`; empty means `None`), and whose side matches `direction`. There must be exactly one.
  - **Save directly** only when the candidate claims **exactly that stream's rows**:
    - the set of rows the candidate would win, by object identity, equals the set of that stream's rows on the candidate's side (`amount > 0` for outflow, `< 0` for inflow);
    - and `taken` is empty.

    This rules out both overreach (rows of another group, or a sibling plan) and partial coverage (a short or fallback `pattern_hint` that matches only some of the stream's rows).
    - On a save, the route redirects to `/recurring?marked=<new id>#not-counted`.
  - **Already marked.** If the stream is not found, but a saved rule with `action='not_recurring'` has the same pattern, direction and range, the route redirects to `/recurring?marked=<that id>#not-counted`. This makes a double click or a stale page idempotent.
  - **Otherwise** (no or ambiguous stream, rows not equal, rows taken, invalid fields, no keys, over 500 keys) it redirects to `GET /recurring/rules/new` with the same label, pattern, direction and amounts, plus `action=not_recurring&preview=1`. The user then sees the existing preview and saves from there. No 400 page.
  - Posted keys only *locate* the stream. The row-equality check runs on server data, so a stale or forged locator can at worst land on the form.
  - **Support code.**
    - Each stream dict built by `detect_recurring_with_rules`, and each suggestion, gains `rows`: the row objects it was built from. For a suggestion, that is its remaining outflows. These are references, not copies. Every consumer of these dicts (`grep detect_recurring_with_rules`/`detect_bills`/`detect_recurring_from_groups`) is checked so that none serializes or compares whole dicts.
    - `preview` gains `won_rows`, the candidate's rows.
    - A pure helper `quick_mark_verdict(found, preview_result, keys, split_amount, direction)` in `app/recurring_rules.py` returns `'save'` or `'form'`, and is unit-tested.
    - Detection rows already carry `merchant_entity_id`, `merchant_name` and `description` (`_DETECTION_COLUMNS`). `grouping_key` needs nothing new, and nothing reads a new column.
- **Why the match is safe across merges.** `apply_rules` partitions rows per row, independent of group order. `merge_by_descriptor` keeps the same row objects (`[t for g in side for t in g]`). Streams are built only from leftovers. So a stream merged from two index groups has one `stream_keys` holding both keys, and its rows are exactly the rows the candidate must win.
- **Stream keys.** Each non-rule stream and suggestion gets `stream_keys`: the sorted distinct non-empty `grouping_key` values of its `rows`.
  - This is separate from `essential_keys`: income has none of those, and those carry prefixes and amount suffixes.
  - A stream with no keys gets no quick button, only Flag.
- **UI** (`recurring.html`):
  - Every row that has a Flag link today (counted, each not-counted group, income, possibly recurring) gets a small inline **Not recurring** button. It is a `<form method="post">` with hidden fields, styled `btn btn-sm btn-ghost`.
    - Its `title`: "Stop counting this — not a bill, or one you cancelled. Future charges matching it stay hidden too; undo from Not counted → Marked not recurring."
    - Same-amount sub-streams post their pinned amount as both bounds, as their Flag link does today.
    - Rule-built rows keep their badge and get no button.
    - The suggestions' existing "Not recurring" link becomes this button. `has_split` suggestions stay withheld, as today.
  - The Flag link stays.
  - **Notice.** `?marked=<id>` is read with `request.args.get('marked', type=int)`, so a non-integer is ignored. When it names a rule that is in `found.rules`, the page shows a notice card above the figures: "Marked **<label>** not recurring: <N> rows matching "<pattern>" from <sources>." It has an **Undo** button (POST delete). An unknown id shows nothing. It costs no query, because the rules are already loaded.
  - **Undo on the list.** Each "Marked not recurring" row gets an **Undo** button (POST `/recurring/rules/<id>/delete`).
  - The "Not counted" heading gets `id="not-counted"`. With `?marked`, the Marked-not-recurring `<details>` renders `open`.
- **Nothing else changes.** The rule model, the migration, precedence, detection results, the form and the delete route are all untouched. A quick mark saves an ordinary `not_recurring` rule, listed on the Your rules card.

### Alternatives considered
- **B: one-click save with no containment guard**, relying on the notice and Undo to show what was claimed. Simpler, but one click on a check stream or a broad transfer hint would silently claim unrelated rows across groups. That is exactly the risk the form's preview exists for.
- **C: a per-stream "dismiss" flag keyed by stream key (a new table, like essential marks).** This was rejected in the rules work (knowledge 2026-11-07, alternative B), because it duplicates the not-recurring mechanism. Keys are also lost when Plaid re-enriches rows, so a cancelled subscription would silently reappear.
- **D: an inline expanding preview per row** (details or a fetch) with a confirm button. It keeps the preview but costs one `apply_rules` pass per row on page load, or new JavaScript. It is still two clicks, and A already gives the preview exactly when it matters.

## Success criteria
1. **Unit** (`tests/test_recurring_rules.py`, fictional fixtures):
   - `preview` returns the candidate's `won_rows`.
   - `quick_mark_verdict` returns `'save'` when the hint claims exactly the stream's rows. It returns `'form'` when:
     - a row of another group is also won;
     - only some of the stream's rows are won (a hint that falls back to one description);
     - rows are taken from a saved rule;
     - no stream matches the locator.
2. **Detection:** each whole-group bill, income stream, same-amount sub-stream and suggestion carries `rows` and `stream_keys` (its rows' distinct grouping keys). A rule stream carries `stream_keys` of `()`.
3. **Routes** (frozen clock, fictional data):
   - Quick-marking a counted bill saves one `not_recurring` rule and redirects to `/recurring?marked=<id>#not-counted`. The page then no longer counts the bill, lists it under Marked not recurring, and shows the notice (with the pattern) and Undo.
   - Quick-marking an income stream saves an inflow rule.
   - Quick-marking a same-amount sub-stream saves a rule ranged to exactly that amount, and the sibling plan stays counted.
   - Quick-marking a stream merged from two index groups (`merge_by_descriptor`) saves and claims both groups' rows.
   - A pattern that would also claim another group's rows saves nothing. A pattern that would claim only part of the stream saves nothing. Both redirect to the form with `action=not_recurring` and `preview=1`, and the form renders the preview.
   - Posting the same quick mark twice saves one rule. The second post redirects to `?marked=<first id>`.
   - Invalid input (a pattern under 3 characters, no key, or over 500 keys) saves nothing and redirects to the form.
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
