# Scratchpad: display-account-balances

> **Ephemeral working memory.** Most of what lands here is noise — small
> decisions that don't matter, dead ends, momentary confusion. At feature
> completion, run `minerva:promote`: significant items get promoted to
> `.minerva/knowledge/`, `proposal.md` gets updated to match reality, and
> the raw scratchpad is archived.

## Review triage 2026-05-20
- [SUGGESTED] #1 low app/templates/index.html:13 — balance rendered without thousand separators ($1234.56)
- [IGNORED]   #2 low app/sync.py::_refresh_balances — only catches plaid.ApiException; matches existing pattern
- [IGNORED]   #3 low app/sync.py::_refresh_balances — last_synced_at overwrite is microsecond-harmless

## Review finding 2026-05-20

- **Balance display lacks thousand separators.** Both the headline balance and the "This filter:" secondary line use `"%.2f"|format(...)`, producing `$1234.56` instead of `$1,234.56`. Readability degrades on four-figure balances. Future cosmetic pass: switch to a format that includes the grouping separator (e.g. a custom Jinja filter or `{:,.2f}`) applied consistently to both the headline and the filter total.

