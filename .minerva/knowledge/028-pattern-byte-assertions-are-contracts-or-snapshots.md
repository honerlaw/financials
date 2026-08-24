# The route tests assert rendered bytes — tell a contract from a formatting snapshot

**Date**: 2026-08-24
**Type**: pattern
**Summary**: `tests/test_routes.py` asserts literal substrings of rendered HTML, and those assertions are two different things — semantic contracts whose failure means the change is wrong, and formatting snapshots whose failure is a decision to make; editing the first to get green is how a real regression ships.
**Context**: .minerva/work/2026-08-24-ui-design-system

## Finding

The dashboard's route tests check rendered bytes:

```python
assert b'Due Dec 25' in res.data
assert b'Vested' not in res.data
assert b'$12345.67' in res.data
```

These look alike and are not alike. Replacing Bootstrap
([[025-decision-hand-authored-design-system]]) turned three of them red at once,
and the three needed opposite treatment.

## The two kinds

**Contracts** — encode a semantic guarantee. A failure means the change broke
something; fix the code.

- `b'Vested' not in res.data` / `b'Unvested' not in res.data` — an account with
  no vesting schedule must render *no* vested row, because `$0.00` would assert
  that nothing has vested, which is a different and false claim
  ([[021-decision-plaid-vested-value-piggyback-on-sync]]).
- `b'Due ' not in res.data`, `b'Overdue' not in`, `b'min $' not in` — same shape
  for liabilities. Note the **trailing space** on `b'Due '`, and that it matches
  anywhere on the page: introducing the word "Due" in an unrelated heading or
  `aria-label` fails a test about the account card.
- `'—' in res.data` — a missing balance renders an em dash, never `$0.00`.
- `b'>Transactions<'` — nav label text, and a markup constraint: the label may not
  gain surrounding whitespace or a wrapping element.
- `'Total $950.00' in body` — proves the month total is *institution-scoped*. The
  word `Total` is the probe's anchor; without it the assertion would match any
  figure on the page. When a redesign dropped the word, the fix was to restore it
  in the template, **not** to weaken the assertion to a bare `$950.00`.

**Formatting snapshots** — pin an incidental rendering. A failure is a decision,
and editing the literal is legitimate.

- `b'$12345.67'`, `b'$8900.00'`, `b'$1234.56'` — these broke by design when
  thousands separators landed, and were updated to `$12,345.67` and friends.
  (`b'$432.10'` never changed: grouping is a no-op below four digits.)

## The rule

Before editing any assertion to get green, classify it. **A contract failing
means your change is wrong.** A snapshot failing means you changed presentation
on purpose — update the literal, and say so in the diff so a reviewer can see it
was classified rather than silenced.

The asymmetry is what matters: silencing one contract assertion ships a real
defect, and every one listed above guards a decision recorded elsewhere in this
wiki. Refusing to edit *any* test is the opposite failure — it forces genuine
formatting work to be abandoned or faked.

## Implications

- This suite is an excellent regression harness for a presentation rewrite: it
  pins semantics while leaving styling free. All 268 tests were used exactly that
  way, with three snapshot literals edited and no contract touched.
- It is blind to layout and to computed style. It cannot see a mis-specified
  utility ([[027-pattern-utility-classes-lose-to-element-qualified-rules]]), a
  contrast failure, or a class name that crosses into a JSON payload
  ([[026-constraint-css-class-names-cross-the-json-boundary]]). Green here is not
  evidence the page looks right.

## Related

- [[025-decision-hand-authored-design-system]] — the rewrite that forced the distinction.
- [[027-pattern-utility-classes-lose-to-element-qualified-rules]] — a defect class this suite structurally cannot observe.
- [[026-constraint-css-class-names-cross-the-json-boundary]] — a contract the suite checks only the key of, never the value.
- [[021-decision-plaid-vested-value-piggyback-on-sync]] — the null-is-not-zero decision several contract assertions guard.
- [[004-pattern-seed-relative-dates-in-time-sensitive-tests]] — see also, another way these tests encode more than they appear to.
- [[034-pattern-only-the-call-site-is-authoritative-for-runtime-behaviour]] — see also
