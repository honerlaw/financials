# The UI is a hand-authored token-driven stylesheet, not Bootstrap and not Tailwind

**Date**: 2026-08-24
**Type**: decision
**Summary**: Bootstrap 5 was replaced by `app/static/app.css` — CSS custom properties defining a light and a dark token set, consumed by component rules that contain no literal colours — chosen over Tailwind because this repo has no Node toolchain and because two Bootstrap class names are hard-coded in a JSON payload the CSS cannot rename.
**Context**: .minerva/work/2026-08-24-ui-design-system

## Context

The app rendered as stock Bootstrap 5.3.0 from a CDN plus two lines of inline
override. No type scale, no spacing rhythm, no palette, no dark mode; money
formatted with `"%.2f"` so a real account read `$615966.75` while the SMS digest
already said `$615,966.75`.

The framing question was whether a "much nicer UI" required moving to React. It
did not, and that is the load-bearing part of this decision: the app is 7 Jinja
templates of mostly read-only tables. What made it look plain was the absence of
design, not the absence of a framework.

## Decisions

1. **Hand-authored CSS over Tailwind.** Tailwind needs either a Node build stage
   or the standalone binary added to a `Dockerfile` that is otherwise a clean
   `pip install` with a pinned Doppler CLI ([[011-decision-doppler-hybrid-config]]).
   It also needs a custom theme *purely* to keep `text-danger` / `text-success`
   alive, because those are not stock Tailwind utilities and
   [[026-constraint-css-class-names-cross-the-json-boundary]] forbids renaming
   them. All toolchain cost, no visual benefit at 7 templates. The Play CDN was
   rejected outright — it is production-discouraged and would reinstate the
   CDN-script pattern this change existed to remove.

2. **Tokens are the only place colours live.** `:root` defines the light set; a
   `@media (prefers-color-scheme: dark)` block redefines the same names. No
   component rule contains a literal colour, so re-theming is a token edit and
   dark mode cannot drift out of sync with light.

3. **Two text tiers, not three — and the third is arithmetically impossible.**
   A `--text-subtle` tier was written, shipped into review, and deleted. It
   measured **2.58:1** on `--surface` and **2.34:1** on `--surface-2` against a
   WCAG AA floor of 4.5:1, while being applied to every table header on every
   page. Clearing AA on `--surface-2` requires a value no lighter than
   `--text-muted` (`#667085`, 4.51:1) — so a *lighter* third tier could only ever
   have existed by failing contrast. Anyone reaching for a fainter grey for small
   text is reaching for a contrast bug.

4. **Currency is grouped and tabular.** All amounts use `{:,.2f}` / `{:,.0f}`,
   matching `app/notifications.py`, with `font-variant-numeric: tabular-nums` so
   columns align on the decimal. The formatting is done in-template at 15 call
   sites rather than via a Jinja filter, because the app registers no template
   filters at all and adding one means editing `app/__init__.py` — barred at the
   time by a concurrent work unit's file contract. A filter is the better
   long-term design and is filed as a follow-up.

5. **The navbar wraps rather than collapsing.** There was no Bootstrap collapse
   behaviour to inherit — the old navbar had none — so at this link count
   flex-wrap beats introducing a disclosure widget.

## Implications

- Visual verification needs a running app. The Alembic chain is Postgres-only
  ([[017-pattern-migration-chain-is-postgres-only]]), so a preview harness boots
  the app on SQLite via `db.create_all()` and seeds the conditional branches the
  templates carry — null balance, overdue liability, vested-with-null-unvested,
  cancelled stream. Screenshots caught two defects the 268-test suite could not:
  a specificity bug ([[027-pattern-utility-classes-lose-to-element-qualified-rules]])
  and the contrast regression above.
- Semantic states that look like styling are not styling. Dimmed-plus-neutral
  for a lapsed stream ([[005-decision-bills-inactive-override]]) and an em dash
  rather than `$0.00` for a null
  ([[021-decision-plaid-vested-value-piggyback-on-sync]]) both survive as
  explicit design-system states, because a design pass is exactly what tends to
  normalise them away.

## Related

- [[026-constraint-css-class-names-cross-the-json-boundary]] — the coupling that ruled out renaming two class names, and with them Tailwind's default palette.
- [[027-pattern-utility-classes-lose-to-element-qualified-rules]] — the specificity trap this stylesheet hit twice.
- [[028-pattern-byte-assertions-are-contracts-or-snapshots]] — how the existing suite was used as the regression harness for the rewrite.
- [[005-decision-bills-inactive-override]] — lapsed-state semantics carried through the redesign.
- [[021-decision-plaid-vested-value-piggyback-on-sync]] — null-is-not-zero semantics carried through the redesign.
- [[017-pattern-migration-chain-is-postgres-only]] — why the preview harness uses `db.create_all()`.
