# The user corrects /recurring with description rules that claim rows before detection

**Date**: 2026-11-07
**Type**: decision
**Theme**: recurring-detection
**Summary**: A `RecurringRule` (raw-description substring + direction + optional amount range → recurring / not recurring) claims matching rows from the detection groups per request; each rule's rows form one stream, so a rule can split one payee out of a mixed group.
**Context**: .minerva/work/2026-11-07-recurring-rules (see git history if the worktree has been cleaned up)

## Context

Cadence-only detection has three ways to get a real bill wrong that no constant fixes:
- Plaid categorizes the bill as a transfer, so it is excluded.
- The bill is paid by transfer. Normalization strips the masked account digits, so its rows sit
  in one group with account-to-account transfers.
- The bill is paid by check. Normalization strips the check number, so every check shares one
  "Check #…" group, and only the amount tells one payee's checks apart.

A per-stream on/off flag (by merchant key or `MerchantGroup.id`) fixes only the first case.

## Finding

1. **Rules match raw rows, not groups.** `app/recurring_rules.py::apply_rules(groups, rules)`
   is pure. A rule claims a row when all of these hold:
   - its `direction` matches the row's sign (outflow `amount > 0`, inflow `amount < 0`);
   - its `pattern` is a case-insensitive substring of the raw `description` (raw, so masked
     digits stay matchable);
   - the row's `abs(amount)` falls inside its inclusive optional range.

   A minimum of 0 is stored as no minimum.
2. **Precedence is global.** When several rules match a row, the winner is:
   1. a rule with a range;
   2. then the longest pattern;
   3. then the lowest id.

   An unsaved candidate ranks after every saved rule. Rows are partitioned by position, so two
   value-equal SQLAlchemy rows are both claimed or both kept. The form's preview runs the saved
   rules plus the candidate and reports rows taken from, or lost to, saved rules, keyed by rule
   id.
3. **Detection runs on what is left, then on each rule.** The leftover groups go through
   `merge_by_descriptor` and detection unchanged. Claiming rows can change a leftover group's
   span or dominant descriptor, and so whether it merges.

   Each rule builds one stream (`detect_recurring_with_rules`), and the rule's action decides it:
   - **Recurring outflow.** Never excluded as a transfer. If no cadence is detected, it is
     forced to monthly through `_build_stream(fallback_cadence=…)`. A forced stream is estimated
     as the larger of the per-date P75 and the P75 of its calendar-month totals. Its status is
     paid if anything posted this month, and upcoming otherwise, never "Unpaid". A detected
     annual cadence stays annual, and the stream is still excluded when inactive.
   - **Recurring inflow.** Counted income without INCOME-category evidence, but only with a
     detected cadence. Income is never forced, because income must err low.
   - **Not recurring.** The rows leave detection and are listed under "Marked not recurring"
     with their source groups, so nothing leaves the page unseen.
4. **No grouping or index change.** Rules cost one plain-row query plus a linear pass.
   `GROUPING_ALGO_VERSION` and the persisted index are untouched. Rules are read as plain rows,
   like transactions, so the commit after detection cannot expire them into per-rule SELECTs.
5. **SameSite=Lax is set app-wide.** The session cookie is the only credential. Lax keeps it
   off cross-site POSTs, which protects the new rule forms and the existing sync, digest and
   removal endpoints alike.

## Implications

- **This deliberately overrides knowledge 003 for user-named rows.** A rule's range is an
  amount gate, and its forced monthly cadence bypasses the cadence gate. Both apply only to the
  rows the user named, and expenses err high. If a payee's price drifts out of the range, its
  rows fall back into their group. The card's "last matched" date shows that a rule has stopped
  matching.
- **Rules only see grouped rows.** A row with no groupable merchant key (a purely numeric
  description) is in no group and cannot be claimed. The form says so.
- **A broad pattern can claim rows the user did not intend.** The preview's per-source "N of
  M rows" and amount range make this visible before saving, and the card shows it after.
- **A rule-built biweekly-by-date bill can still show a false "Unpaid".** For example, a bill
  paid on the 1st and 15th that is detected as biweekly. This is the same ±6-day window problem
  as issue #58 (knowledge 006), which a rule can now surface by moving such a stream from
  Transfers into the counted list.

## Related
- [[003-decision-subscriptions-cadence-only-detection]] — overridden for user-named rows only (range gate, forced monthly)
- [[2026-11-06-decision-recurring-page-and-income-rule]] — the manual income override it anticipated; income still never forced
- [[2026-10-26-decision-fixed-monthly-bills-total]] — rules read only `_DETECTION_COLUMNS` and load as plain rows
- [[2026-11-07-decision-merge-groups-renamed-by-plaid]] — leftover groups still merge; claiming can change the result
- [[006-decision-bills-payment-status-algorithm]] — forced streams skip the ±6 window; other streams keep it (issue #58)
- [[017-pattern-migration-chain-is-postgres-only]] — the new table's migration was verified in isolation
