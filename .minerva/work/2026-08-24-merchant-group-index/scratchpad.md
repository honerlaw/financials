# Scratchpad: merchant-group-index

> **Ephemeral working memory.** Most of what lands here is noise — small
> decisions that don't matter, dead ends, momentary confusion. At feature
> completion, run `minerva:promote`: significant items get promoted to
> `.minerva/knowledge/`, `proposal.md` gets updated to match reality, and
> the raw scratchpad is archived.

## Cross-session constraints (2026-08-24)

Session `financials-24` is doing a Bootstrap → Tailwind redesign in parallel,
scoped to `app/templates/*.html` and `app/static/*` — **no .py files**. Agreed
contract:

- Their diff is presentation-only; the `/subscriptions` and `/bills` view
  functions and the dict keys they pass to templates are mine and stay stable.
- **Do not touch `app/routes.py:261`** — `'amount_class': 'text-danger' if
  txn.amount > 0 else 'text-success'` in the `/api/transactions` payload. The
  infinite-scroll JS applies that string verbatim, and they are keeping
  `.text-danger` / `.text-success` as live class names in the new stylesheet
  precisely because routes.py is not theirs to edit. It is the one string
  coupling the two diffs. Not in this unit's scope anyway — noted so it does not
  get "cleaned up" opportunistically.
- Whoever merges first, the other rebases; no sequencing needed.

Also in flight earlier today: `financials-4d` shipped PR #35 (da2cda1) and the
knowledge reconcile #36 (adfaf78). This branch is based on adfaf78. Their diff
touched `_refresh_balances` / `_refresh_investments` bodies and added
`_create_account_if_missing`; `_upsert_transactions` and the tail of
`_sync_institution` — the two places this unit edits in sync.py — were left
untouched. `tests/test_sync.py` grew ~230 lines and its import block is the
likely conflict surface if this unit appends test cases there.
