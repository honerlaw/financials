# Scratchpad: ui-design-system

## Balanced decisions 2026-08-24

- [reviewed — folded] scope check: single unit, presentation-layer only (Skeptic verdict `revise`, 6 concerns). Folded 4: (#1) the Tailwind-vs-hand-authored choice was undisclosed in the artifact while already communicated to the peer session as "Tailwind" — resolved explicitly at intake instead of mid-execution, and the Skeptic's catch that `text-danger`/`text-success` are not stock Tailwind utilities turned Tailwind from default into dominated; (#2) "two class names" understated the preserved vocabulary — scope now names the full Bootstrap semantic surface plus the 4 class strings in index.html's inline JS; (#3) knowledge 005/021 promoted from cited prose into named acceptance criteria 4 and 5; (#4) the interleaving of `sendDigest`'s expiry logic with the class assignments being edited got its own criterion 6. Not folded: (#6) confirmed non-issue by the Skeptic itself.
- [escalated to user] scope size + approach + review cadence: Skeptic concern #5 argued the breadth of a 7-template one-pass rewrite exceeds this rung's small-to-medium bar given zero human visual review. Partly disagreed — the change is reversible, behaviour-free and test-guarded — but taste is not verifiable by tests or by a subagent, so escalated rather than self-confirmed. User chose: refined light + OS-following dark; hand-authored CSS over Tailwind; ship all 7 pages in one pass and review at the PR (declined the mid-flight checkpoint and declined escalating to a heavier orchestrator). This answer also resolves the approach-selection gate directly — no second Skeptic dispatched to re-litigate a question the user just decided.
- [decided] whole-proposal soundness: sound (solo gate). Presentation-only, no public interface, no schema, no route or template-context change; fully reversible as a CSS/markup diff. The one cross-cutting coupling (`routes.py:261` → `amount_class`) is handled by preserving the two class names rather than by editing Python.

## Coordination

Disjoint file contract agreed with session `financials-a5` (work unit
`2026-08-24-merchant-group-index`), reciprocated by it:

- **This unit**: `app/templates/*`, `app/static/*`. Nothing else.
- **That unit**: `app/routes.py`, `app/models.py`, `app/sync.py`,
  `app/subscriptions.py`, `app/bills.py`, `app/merchant_groups.py`, a migration,
  tests. It does not touch templates or static.
- Shared coupling, recorded in both scratchpads: `app/routes.py:261` emits
  `amount_class` as a Bootstrap class name. Neither side renames it; this side
  keeps `.text-danger`/`.text-success` live in the new CSS. **Do not
  opportunistically tidy that line.**
- Whoever merges first, the other rebases. No sequencing needed.

`app/notifications.py` is out of bounds for a separate reason: its message text
is filed with the carrier for A2P 10DLC and changing it forces a campaign
re-filing (knowledge 022). It already formats currency correctly.

## Test-suite semantics (from peer review by `financials-4d`, verified)

The route tests assert on literal rendered bytes. Two distinct kinds:

- **Contracts** — a failure means this change broke something:
  `b'Vested' not in`, `b'Unvested' not in`, `b'Due ' not in` (note the trailing
  space; matches anywhere on the page), `b'Overdue' not in`, `b'min $' not in`,
  `'—' in`, `b'>Transactions<'` (the label may not gain whitespace or a
  wrapping element).
- **Formatting snapshots** — a failure is a decision, not a bug:
  `b'$12345.67'`, `b'$8900.00'`, `b'$1234.56'`, `b'$432.10'`. These break by
  design when thousands separators land.

`tests/test_routes.py:666` asserts only `'amount_class' in item` (key presence,
not value), so it imposes no constraint beyond the one already handled.

## Preview harness

Lives outside the repo, at the session scratchpad's `preview.py`, deliberately —
the zero-`.py`-changes constraint means the render harness must not become review
surface. It boots the real app on SQLite via `db.create_all()` (the Alembic chain
is Postgres-only — knowledge 017) and seeds data exercising every conditional
branch: overdue liability, future-due liability, null balance, vested+unvested,
vested-with-null-unvested, plain depository, inactive streams, and a sync error
row. Serves on :5055, password `preview`.

## Implementation notes
