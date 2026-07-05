## Goal

Make the dashboard spending charts interactive: clicking a **week card** or a
**day bar** filters the transactions table (and its infinite scroll) to that
window. Selecting a week shows that Sun–Sat week's transactions; selecting a
day shows that day's.

## Why

The 010 spending section shows *how much* was spent per day/week but there's no
way to drill from a spike into the actual transactions behind it. Making the
chart elements clickable turns the chart into a navigation control over the
existing table — "what did I spend on the week I went over budget?" — reusing
the table that's already on the page.

## Status

Draft

## Approach

Reuse the existing URL-param + server-filter pattern (as `?institution=` /
`?month=` already do). Add a date **window** via `?start=YYYY-MM-DD` (inclusive)
and `?end=YYYY-MM-DD` (exclusive).

**`app/routes.py`**:
- `_parse_iso(s)` → `date.fromisoformat` or `None` (tolerant of missing/garbage).
- `_table_date_bounds(request)` → effective `(start, end_exclusive)` for the
  table: a valid `start`/`end` window takes precedence over `?month=`; falls
  back to `_month_bounds(month)` otherwise; `(None, None)` when neither is set.
- `index()` and `transactions_json()` both filter the transaction query via
  `_table_date_bounds` (replacing the duplicated month-only filter). The
  account-totals strip also uses the effective window so it stays consistent
  with the filtered table.
- The spending chart section stays scoped to `?month=` (default current month)
  — independent of the window — so the user can keep clicking to pick windows.
- `index()` passes `window_active` + `window_label` (e.g. "Jul 5 – Jul 11,
  2026", or a single date for a day) and the raw `start` so the template can
  render an active-window indicator and highlight the selected card.

**`app/templates/index.html`**:
- Week cards and day bars get `cursor:pointer`, a `title`, and an `onclick`
  calling a JS `selectWindow(startISO, days)` helper that sets `start`/`end`
  (computing `end = start + days` client-side), drops `page`, preserves the
  other params, and navigates. Weeks pass `days=7`, days pass `days=1`.
- An active-window indicator ("Showing <label> · Clear") appears above the
  table when a window is active; `clearWindow()` drops `start`/`end`/`page`
  while preserving `month`/`institution`. The selected card is visually marked.

**`tests/test_routes.py`** (or `test_spending.py`): `index()` and
`/api/transactions` return only transactions within a `start`/`end` window;
window precedence over `month`; malformed `start`/`end` ignored (no 500).

## Success criteria

1. Clicking a week card filters the table + infinite scroll to that Sun–Sat
   week via `?start`/`?end`.
2. Clicking a day bar filters to that single day.
3. `/api/transactions` honors `start`/`end`, so infinite scroll stays within
   the selected window.
4. A window indicator shows the active window with a Clear control that returns
   to the month view; the institution filter is preserved across selection.
5. `start`/`end` take precedence over `month` for the table and account-totals
   strip; the spending chart stays scoped to the month.
6. Malformed/partial `start`/`end` is ignored gracefully (no 500), falling back
   to the month filter.
7. `pytest` passes, with new tests covering window filtering in `index()` and
   `/api/transactions`.

## Open Questions

- Should selecting a window also re-scope the spending chart to that window?
  (Current design: no — the chart stays on the month so it remains a stable
  picker. Revisit if drilling should zoom the chart too.)
