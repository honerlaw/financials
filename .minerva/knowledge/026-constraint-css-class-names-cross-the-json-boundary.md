# `routes.py` emits CSS class names into JSON — renaming either side breaks colour silently

**Date**: 2026-08-24
**Type**: constraint
**Summary**: `app/routes.py:261` puts the literal strings `text-danger` / `text-success` into the `/api/transactions` payload and the infinite-scroll script applies them verbatim to appended rows, so those two class names are a cross-layer contract that no test asserts and no framework migration may quietly rename.
**Context**: .minerva/work/2026-08-24-ui-design-system

## The constraint

`app/routes.py`, in the `/api/transactions` payload builder:

```python
'amount_sign': '-' if txn.amount > 0 else '+',
'amount_class': 'text-danger' if txn.amount > 0 else 'text-success',
```

`appendRow` in `index.html`'s infinite-scroll script applies that string directly
as a class on the amount cell. So a presentation-layer name is chosen by Python,
travels through JSON, and is resolved by CSS.

## Why it matters more than it looks

**Nothing catches a break.** `tests/test_routes.py` asserts only that the
`amount_class` *key* is present, never its value. No template renders the string.
The failure mode is that the first page of transactions is coloured correctly and
every lazily-appended row after it renders in default body text — visible only by
scrolling far enough to trigger the observer, in a browser, on a dataset large
enough to paginate.

**It constrains choices that look unrelated to it.** When Bootstrap was replaced
([[025-decision-hand-authored-design-system]]), this coupling is what ruled
Tailwind out as much as the missing Node toolchain did: `text-danger` and
`text-success` are not stock Tailwind utilities, so Tailwind would have needed a
custom theme block existing solely to satisfy a line of Python that the styling
work was contractually barred from editing.

## Rules

- Do not rename `text-danger` / `text-success` on either side independently. They
  are defined in `app/static/app.css` explicitly to honour this payload, with a
  comment saying so.
- Do not "tidy" `routes.py:261` opportunistically. It looks like a layering smell
  and reads as an easy cleanup; it is load-bearing until both sides move together.
- The correct fix, when someone does it deliberately, is to emit a *semantic*
  value (`'outflow'` / `'inflow'`) and let CSS own the colour — a two-sided change
  touching Python, JS and CSS in one commit.

## Related

- [[025-decision-hand-authored-design-system]] — the migration this constraint shaped.
- [[028-pattern-byte-assertions-are-contracts-or-snapshots]] — why the suite's silence here is structural, not an oversight.
