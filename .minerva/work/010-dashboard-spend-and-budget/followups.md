# Follow-ups — dashboard-spend-and-budget

Forward-looking items surfaced during work unit 010. Not scheduled; each could
seed its own proposal.

- **Configurable weekly budget.** `$1000` is a hardcoded `WEEKLY_BUDGET`
  constant in `app/spending.py`. Make it user-settable (settings page + a
  stored value), so the tracker isn't fixed.

- **Refine the spend-exclusion set.** The provisional exclusion is Plaid
  `TRANSFER*` / `LOAN_PAYMENTS` primaries, with null-category outflows counted.
  Revisit against real synced data — e.g. whether to also exclude `BANK_FEES`,
  or to reclassify null-category rows once more history has categories.

- **Arbitrary date-range picker.** "Timeframe" is currently month-granularity
  (the existing `<input type="month">`). A start/end date-range control would
  let the user view spend across custom windows.
