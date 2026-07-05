# Follow-ups — chart-click-filters-transactions

- **Optionally re-scope the spending chart to the selected window.** Currently
  the chart stays month-scoped when a day/week window is active (so it remains
  a stable picker). A future variant could zoom the chart to the window too
  (with a "back to month" affordance). Deferred — revisit if drilling should
  zoom rather than just filter the table.

- **Keyboard accessibility for clickable chart elements.** Week cards and day
  bars use `onclick` on `<div>`s without `role="button"`/`tabindex`, so they
  aren't keyboard-focusable. Low priority for this personal app.
