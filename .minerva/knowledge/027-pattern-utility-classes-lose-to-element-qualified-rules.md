# A utility class silently loses to an element-qualified component rule

**Date**: 2026-08-24
**Type**: pattern
**Summary**: `.table th { text-align: left }` has specificity (0,1,1) and beats a bare `.right` utility at (0,1,0), so the utility appears to do nothing — a failure invisible to a suite that asserts on rendered text rather than layout, and only found by looking at a screenshot.
**Context**: .minerva/work/2026-08-24-ui-design-system

## Finding

The hand-authored design system ([[025-decision-hand-authored-design-system]])
pairs component rules with single-class utilities:

```css
.table th { text-align: left; /* … */ }   /* (0,1,1) — class + element */
.right    { text-align: right; }          /* (0,1,0) — class only      */
```

`<th class="right">Amount</th>` renders **left-aligned**. The component rule wins
on specificity, so the numeric column header sat visibly out of line with its own
right-aligned column while all 268 tests passed.

The same shape bit twice more in one stylesheet:

- `.table td { padding: … }` beats `.empty { padding: … }`, so empty-state cells
  ignored their intended padding.
- The reciprocal error is just as easy: a code review recommended *deleting*
  `.table td.empty` as "redundant with `.empty`". It is not redundant — deleting
  it would have silently restored the cramped padding. Both the bug and the
  proposed fix came from the same misreading of the cascade.

## The rule

**A utility only overrides a component rule if it is at least as specific.** When
a component rule is element-qualified, its utilities must be too:

```css
.table th.right { text-align: right; }
.table td.empty { padding: var(--sp-6) var(--sp-4); }
```

Prefer not qualifying component rules by element in the first place
(`.table-head-cell` rather than `.table th`), which keeps the whole utility layer
at uniform specificity. Where element-qualified rules are convenient — styling
`th`/`td` wholesale genuinely is — accept that every utility meant to override
them needs the element in the selector.

## Why testing did not catch it

The suite asserts on rendered *bytes* — `b'Due Dec 25'`,
`b'Vested' not in res.data` ([[028-pattern-byte-assertions-are-contracts-or-snapshots]]).
Class attributes are present and correct in the HTML; only the *computed* style
is wrong. No text-level assertion can observe this, and neither can a subagent
reviewing a diff — the completion Verifier read the same CSS and reported the
criteria met.

**A screenshot found it.** For visual work, rendering the page and looking at it
is not a nicety on top of the tests; it is the only instrument that observes the
class of defect the tests are structurally blind to.

## Related

- [[025-decision-hand-authored-design-system]] — the stylesheet this pattern was found in.
- [[028-pattern-byte-assertions-are-contracts-or-snapshots]] — the suite's assertion style, and why it cannot see layout.
