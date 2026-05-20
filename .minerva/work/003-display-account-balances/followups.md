# Followups: display-account-balances

## 2026-05-20

- **Format balances with thousand separators.** Both the headline balance and the "This filter:" secondary line in `app/templates/index.html` use `"%.2f"|format(...)`, producing `$1234.56` instead of `$1,234.56`. Readability degrades on four-figure balances (the common case for credit-card balances and savings). Replace the format with one that inserts grouping separators (e.g. a small Jinja filter wrapping `f"${value:,.2f}"`) and apply it consistently to both the headline and the filter total so they stay visually aligned.
