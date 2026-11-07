# Proposal: recurring-rules

**Date**: 2026-11-07
**Status**: Implemented

## Goal
The user can correct /recurring themselves when detection gets a stream wrong.

A **rule** matches transactions by text in their description, by direction (money out or money in), and optionally within an amount range. It says one of two things:
- **"recurring"**: count it;
- **"not recurring"**: don't count it.

The rows a rule claims form one stream of their own, so a rule can also pull one payee out of a mixed group. Before saving, the rule form previews exactly which rows it will claim, which streams they come from, and how it interacts with rules already saved. A rule can be started from any row on /recurring, or from scratch, and it can be deleted again.

## Why
Detection has three ways to get a real bill wrong that no detection constant can fix:
- **A bill Plaid categorizes as a transfer.** It is detected, but listed under Not counted → Transfers.
- **A bill paid by transfer.** Normalization strips masked account digits, so its description matches account-to-account transfers. Its rows then sit in one large transfer group.
- **A bill paid by check.** Normalization strips the check number, so every check shares one "Check #…" group. Checks carry no payee, so only the amount tells one payee's checks apart.

The user asked for a way to flag a stream themselves when detection is uncertain: "I can say this is recurring … or not recurring". A per-stream on/off flag would fix the first case, but not the other two. Those need the payee's rows separated out of a mixed group. Production data informed this design. No production names, amounts, counts or account details are recorded here, and all test fixtures are fictional (the repo is public).

## Approach (A — description rules applied per request)
- **Model `RecurringRule`** (new table, Alembic migration verified in isolation per knowledge 017):
  - `id`;
  - `label`: required display name;
  - `pattern`: required, trimmed, at least 3 characters. It matches as a **case-insensitive substring of the raw `description`**, the Plaid name. The raw text is used, not `normalize_merchant`, so masked digits like `****1234` stay matchable;
  - `direction`: required, `'outflow'` or `'inflow'`. A rule only ever claims rows of its sign (outflow = `amount > 0`, inflow = `amount < 0`, Plaid's sign convention; a zero-amount row is claimed by neither);
  - `amount_min` and `amount_max`: optional `Numeric(10, 2)`, inclusive, non-negative, compared against `abs(amount)`. Either one may be set alone;
  - `action`: `'recurring'` or `'not_recurring'`;
  - `created_at`.
- **The amount range is an amount gate.** Knowledge 003 forbids amount gates in automatic detection. A rule's range is a user-stated override of that, scoped to the rows the user named. If a payee's price later moves outside the range, the new rows fall back into their group. The "Your rules" card shows each rule's **last matched date**, so a rule that has stopped matching is visible.
- **Pure application.** `app/recurring_rules.py::apply_rules(groups, rules)` runs over the plain detection rows. It reads only `description` and `amount`, both already in `_DETECTION_COLUMNS` (knowledge 2026-10-26). A future match field must be added there first.
  - A row can be claimed only by rules whose direction matches its sign, whose pattern it contains, and whose range (if any) contains its amount. Each row goes to at most one of those. The winner is:
    1. a rule **with an amount range** (either bound set);
    2. then the **longest pattern**;
    3. then the **lowest id** (the oldest rule). An unsaved candidate in the preview ranks after every saved rule, which is where it lands on save.
  - Rows are partitioned **by identity (position in their group), not by value equality**, so two identical same-day rows are both claimed or both kept.
  - Claimed rows are removed from their groups, and groups left empty are dropped. Rows of the other sign are never touched.
  - For each rule, the result records the rows it **won** and, per source group, that group's display name (`_display_name` of the group before merging, so the page calls these "source groups"), the rows it gave up, and the group's total row count ("N of M rows").
  - The input lists are not mutated, and the result does not depend on the order of the input groups or the rules.
- **Detection.** The groups left after claiming go through `detect_recurring_from_groups` exactly as today, including `merge_by_descriptor`. Removing rows can change a leftover group's dominant descriptor or span, and so whether it merges; this is expected and tested. Each rule's won rows form **at most one stream**, named `rule.label`.
  - `'recurring'`, `outflow` → a bill with payment status and the P75 estimate. It is **never excluded as `transfer`**.
    - Cadence is detected as usual. Only if none is found (irregular, or fewer than 3 occurrences) is it treated as **monthly**, because the user has asserted it recurs. A stream detected as annual stays annual and is excluded as annual.
    - It is still excluded as `inactive` (lapsed, not a current obligation).
    - With a **forced** monthly cadence, the estimate is the larger of the usual per-date P75 × 1 and the P75 of the stream's nonzero calendar-month totals within `ESTIMATE_WINDOW_DAYS`. A stream paid in two irregular parts a month is therefore not understated, and the estimate never falls below ×1.
    - This is a deliberate user-override exception to knowledge 003's cadence-only gate. Expenses err high, which is the safe direction (knowledge 2026-11-06).
  - `'recurring'`, `inflow` → counted income **without** INCOME-category evidence. This is the manual income override that knowledge 2026-11-06 anticipated.
    - Cadence is **never forced**: forcing it would overstate income, and income must err low.
    - If no cadence is detected, the rule is listed on the "Your rules" card as "no regular cadence", and not counted.
  - `'not_recurring'` (either direction) → the won rows leave detection. Nothing silently disappears (knowledge 003: every stream stays listed):
    - a **"Marked not recurring"** group under Not counted shows one row per rule: its label, the number of rows it won, and the names of the streams those rows came from. These rows have their own shape (no cadence, amount or status; they show the rule's direction) and their own template branch. The group renders after the other Not-counted groups, ordered by label, and the Not-counted section renders when this group is the only non-empty one;
    - the "Your rules" card shows the same.
  - A rule that claims nothing produces no stream. It shows as "0 rows" on the card.
  - *As built:* a forced-monthly bill has no due day, so its payment status is "paid" once anything posted this calendar month and "upcoming" otherwise, never "Unpaid" (knowledge 005). The bill/income building is two helpers, `_finish_bill` and `_finish_income`, each taking `override`.
  - `_build_stream(txns, today, fallback_cadence=None)` uses `fallback_cadence` only when `_classify_cadence` returns None. The per-group bill/income building in `detect_recurring_from_groups` is extracted into one helper that takes the group, its stream and an `override` flag. Rule streams and automatic streams then share it instead of duplicating it.
- **UI.**
  - **Flag link.** Every stream row on /recurring (counted, not counted, income) gets a small **Flag** link to `GET /recurring/rules/new?pattern=…&label=…&direction=…`. The direction is pre-filled from the stream's side.
    - The pattern hint is the **longest common prefix** of the stream's distinct raw descriptions, with trailing digits and `#*-` and spaces trimmed (so `Check #1234` and `Check #1301` give `Check`). If that leaves fewer than 3 characters, it falls back to the most common description.
    - A stream carries this as `pattern_hint`.
    - For a bill paid by transfer, the hint stops before the masked digits. The user appends them (e.g. `TO ****1234`), and the preview confirms what that claims. For a check-paid bill, the user adds an amount range.
  - **Add a rule.** The **"Your rules"** card has an **Add a rule** link for things that are not listed at all. Direction defaults to outflow.
  - **Form** (`recurring_rule_form.html`): label, pattern, direction, optional min/max, and action.
    - Whenever the pattern field is filled (including on arrival from a Flag link), the form shows a **preview**. The preview runs `apply_rules` over the **saved rules plus the candidate**. For each source group it shows the name, distinct descriptions, side, and "N of M rows" the candidate would win. It also lists the rows the candidate would take from an existing rule, and the rows it would lose to one. A **Preview** submit (`GET` with the fields) refreshes it after an edit.
    - The preview route loads groups the same way `/recurring` does, and commits after `apply_rules` and detection, as `recurring()` does.
    - **Save** (`POST /recurring/rules`) validates the input, re-renders with errors on failure, and redirects to /recurring on success.
  - **"Your rules" card.** Lists each rule: label, pattern, direction, range, action, rows won, last matched date and source groups. Each rule has a **Delete** button (`POST /recurring/rules/<id>/delete`).
  - **Badge.** Rule-built rows carry a "your rule" badge.
  - **No per-rule queries.** Rules are loaded as plain rows (selected columns, not ORM instances), like detection's transactions, so the commit after detection cannot expire them and the card never re-selects a rule (knowledge 2026-10-26).
  - All new routes are `login_required`.
  - *As built:* a rule-built row shows the badge instead of a Flag link (it is changed by deleting the rule). The preview shows the amount range per source group in place of a side column, since every claimed row is on the rule's one side.
- **Cross-site safety.** `SESSION_COOKIE_SAMESITE='Lax'` is set explicitly. This is an app-wide change to the session cookie: it stops a cross-site POST from carrying the session. That protects the new forms, and also the existing state-changing POST endpoints (sync, digest send, institution removal), which today rely on browser defaults. All of the app's own POSTs are same-origin, so none is affected.
- **Unchanged.** Grouping, the persisted index, `GROUPING_ALGO_VERSION`, the cadence rules and the automatic estimate math are untouched, and /recurring stays the only consumer. Rules cost one extra query plus a linear pass. Badges, counts and source groups all come from that same pass.

### Alternatives considered
- **B — per-stream flags keyed by the stream's `merchant_key`s.** Simpler, with no form. But it cannot split a payee out of a mixed group, so it fails two of the three cases in Why.
- **C — overrides keyed by `MerchantGroup.id`.** Ids change when the index is rebuilt after a `GROUPING_ALGO_VERSION` bump, which would silently orphan the flags. It also cannot split groups.
- **D — rules scoped to one merchant key, with an optional substring and range inside it.** This limits how far a broad pattern can reach. But it breaks when Plaid renames a merchant, which is the problem `merge_by_descriptor` exists for. Global description matching with the form's preview gives the same visibility without that fragility.

## Success criteria
1. **`apply_rules` unit tests** (`tests/test_recurring_rules.py`, fictional fixtures):
   - case-insensitive substring match on the raw description;
   - direction: an outflow rule never claims inflow rows, and the reverse;
   - inclusive `abs(amount)` range, including a min-only and a max-only range;
   - precedence: a range (even half-open) beats a longer pattern; then longer pattern; then lower id;
   - claimed rows leave their groups, and emptied groups are dropped;
   - two identical same-day rows are both claimed: the rule won 2 rows and 0 are left over;
   - each rule records the rows it won and, per source group, "N of M";
   - a rule matching nothing claims nothing;
   - the input is not mutated;
   - the result is independent of group order and rule order;
   - a pattern plus amount range takes only the matching subset of a mixed check-like group.
2. **Detection tests:**
   - an outflow `'recurring'` rule over transfer-categorized outflows yields a counted bill named by its label;
   - irregular outflows under a `'recurring'` rule are counted as monthly;
   - a forced-monthly stream paid twice a month at irregular dates is estimated from its monthly totals, not one payment;
   - an outflow rule whose pattern also matches regular inflows counts only the bill, and the inflows stay in their group;
   - an inflow `'recurring'` rule over uncategorized regular inflows yields counted income;
   - irregular inflows under an inflow `'recurring'` rule are not counted;
   - an inactive `'recurring'` outflow is not counted;
   - a `'recurring'` rule whose rows are annual stays annual;
   - a `'not_recurring'` rule removes a previously counted bill from Counted expenses and from the headline, and lists it under "Marked not recurring" with its source group's name;
   - claiming rows can change a leftover group's dominant descriptor, and with it the result of `merge_by_descriptor`.
3. **Route tests:**
   - `POST /recurring/rules` creates a rule and redirects;
   - invalid input re-renders with an error and creates nothing: missing label, a pattern under 3 characters after trimming, an unknown action or direction, unparseable or negative amounts, min > max;
   - Preview lists the rows the rule would claim, with "N of M";
   - Preview shows rows lost to a saved rule that outranks the candidate, and rows the candidate takes from a saved rule it outranks;
   - `POST /recurring/rules/<id>/delete` removes the rule;
   - every new route redirects to /login when logged out;
   - a stream's Flag link carries its trimmed common-prefix pattern hint (e.g. `Check` for numbered checks, `TRANSFER TO` for `TRANSFER TO ****1234` / `TRANSFER TO ****5678`) and its direction;
   - Add a rule opens the form with direction outflow;
   - the "Your rules" card shows each rule's rows won, last matched date, and "0 rows" for a rule that claims nothing;
   - a rule-built row carries the "your rule" badge;
   - the "Marked not recurring" group renders when it is the only Not-counted group;
   - the session cookie is `SameSite=Lax`.
4. **Migration** verified in isolation on SQLite (stamp the parent, upgrade, downgrade), per knowledge 017.
5. `uv run pytest` passes, including the /recurring query-count test, which must not grow with transaction count. It is extended so the page issues the same number of queries with 1 rule as with 10.
6. **After deploy**, the classifications the user gave in this conversation are entered as rules on production through the new form. These production writes are user-directed. Each rule is saved only after its preview is checked, and a rule shown to be wrong is deleted. /recurring then counts those streams.
   - If a payee cannot be isolated (for example, check amounts that overlap other checks, or a transfer pattern that also claims unrelated transfers), report that to the user rather than call the criterion met.
   - The outcome is reported to the user only. Nothing real is committed.

### Input handling (as built)
- Submitted rules must state direction and action. Only the GET form defaults them (money out, recurring).
- Label and pattern are stripped of control characters, because Postgres rejects NUL.
- A minimum of 0 is stored as no minimum, so it cannot rank as a range.
- Preview counts are keyed by rule id and show each rule's pattern, since labels need not be unique.
- The Preview button skips browser validation, so it works before a name is typed.

## Known consequences
- A rule can move a stream paid twice a month on fixed days (detected biweekly) from Transfers into the counted list. There, the existing ±6-day payment window can show a false "Unpaid" (knowledge 006). This is the same class of problem as issue #58.

## Open Questions
- Rules see only rows that belong to some merchant group. A row whose merchant key has no group, or whose normalized key is empty (a purely numeric memo), cannot be claimed. That is rare, and accepted.
- A broad pattern can still claim rows the user did not intend. The form's preview and the source-stream list on the card make that visible before and after saving.
- A payee whose price drifts out of a rule's range stops matching. The card's last matched date makes this visible; the user widens the range.
