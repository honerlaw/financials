# Scratchpad: ui-design-system

## Balanced decisions 2026-08-24

- [reviewed — folded] scope check: single unit, presentation-layer only (Skeptic verdict `revise`, 6 concerns). Folded 4: (#1) the Tailwind-vs-hand-authored choice was undisclosed in the artifact while already communicated to the peer session as "Tailwind" — resolved explicitly at intake instead of mid-execution, and the Skeptic's catch that `text-danger`/`text-success` are not stock Tailwind utilities turned Tailwind from default into dominated; (#2) "two class names" understated the preserved vocabulary — scope now names the full Bootstrap semantic surface plus the 4 class strings in index.html's inline JS; (#3) knowledge 005/021 promoted from cited prose into named acceptance criteria 4 and 5; (#4) the interleaving of `sendDigest`'s expiry logic with the class assignments being edited got its own criterion 6. Not folded: (#6) confirmed non-issue by the Skeptic itself.
- [escalated to user] scope size + approach + review cadence: Skeptic concern #5 argued the breadth of a 7-template one-pass rewrite exceeds this rung's small-to-medium bar given zero human visual review. Partly disagreed — the change is reversible, behaviour-free and test-guarded — but taste is not verifiable by tests or by a subagent, so escalated rather than self-confirmed. User chose: refined light + OS-following dark; hand-authored CSS over Tailwind; ship all 7 pages in one pass and review at the PR (declined the mid-flight checkpoint and declined escalating to a heavier orchestrator). This answer also resolves the approach-selection gate directly — no second Skeptic dispatched to re-litigate a question the user just decided.
- [reviewed — clean] completion verification: Verifier verdict `accept` — all 9 criteria independently reproduced (suite re-run, diff re-read, live HTML curled). Its targeted hunt for dead Bootstrap classes left behind with no CSS backing them returned zero hits across every template and JS file, and it confirmed `.text-danger`/`.text-success` are defined (app.css:485-486) — the failure no test could catch. It verified criteria 8/9 by CSS audit rather than rendering (no browser in its sandbox); those were verified here by actual light/dark/390px screenshots, so the pair is covered by different methods rather than by one method twice. Nothing folded; nothing dismissed.
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

### Implementation log

- `app/static/app.css` is new (~470 lines): token block (light `:root` + a dark
  override under `prefers-color-scheme`), then components consuming tokens only.
  No literal colours below the token block, so re-theming is a token edit.
- **CSS specificity trap, caught by screenshot rather than by tests.** `.table th`
  sets `text-align: left` at specificity (0,1,1), which silently beats a bare
  `.right` (0,1,0) — the Amount column header drifted out of line with its own
  column while every test still passed. Fixed with `.table th.right`. Same class
  of bug applied to `.empty`'s padding inside `.table td`. Worth remembering:
  a utility class layered on top of an element-qualified component rule loses,
  and nothing in a text-assertion suite can see it.
- Criterion 3 was self-contradictory as first written (criterion 2 authorises
  test-literal edits; criterion 3 said zero `.py` anywhere). Narrowed to
  `app/**.py`, which is what the peer contract actually covers.
- The "Total $X" string: moving the month total into the headline dropped the
  literal `Total ` prefix and broke `test_dashboard_spending_honors_institution_filter`.
  That test probes for the contiguous string to prove the total is filter-scoped,
  so the fix was to restore the word in the template — NOT to weaken the probe to
  a bare `$950.00`, which could match any other figure on the page.
- Three currency literals updated in `tests/test_routes.py` (`$1234.56`,
  `$12345.67`, `$8900.00`), each a formatting snapshot rather than a contract.
  No contract assertion was touched.

### Verified by rendering (preview harness, seeded edge cases)

- null balance → `—`, never `$0.00` (the `$0.00` on that card is the *filter
  sum*, which is genuinely zero and rendered that way before this change too)
- `Rollover IRA` (vested set, unvested NULL) → `Unvested —`, row still present
- account with no equity data → no `Vested` row at all
- overdue liability → red `Overdue Aug 21`; future → `Due Sep 5` + `min $35.00 due`
- cancelled stream → dimmed row + neutral `Inactive` badge on both
  `/subscriptions` and `/bills` (knowledge 005)
- light and dark both render; mobile at 390px wraps with no page overflow

## Minerva audit 2026-08-24 (spec fidelity + knowledge compliance)

Spec fidelity: matches the proposal. One drift corrected — the Scope sentence
named the inline `<script>` blocks but not `app/static/chat.js`, which carries
the same dead-Bootstrap-class risk and had to be converted too. Proposal updated.

Knowledge compliance: 005 (lapsed ≠ unpaid) ✓, 021 (null ≠ zero) ✓, 012/019
(expiry detection) ✓ untouched, 022 (A2P message text) ✓ `notifications.py` never
opened, 017 (Postgres-only migration chain) ✓ n/a but is what forced the preview
harness onto `db.create_all()`.

### TODO — the infinite-scroll fetch still has the bug knowledge 019 describes

`index.html`'s IntersectionObserver fetch against `/api/transactions` still keys
session expiry on "response is not JSON":

```js
if (!(r.headers.get('content-type') || '').includes('application/json')) {
  observer.disconnect();
  window.location.href = '/login';
```

That is exactly the conflation knowledge 019 documents and fixed *for the digest
button only*: non-JSON is the union of "session expired" and "endpoint crashed",
and only one of those is cured by logging in again. If `/api/transactions` ever
throws, the user is bounced to `/login` with a healthy session and the error text
discarded — the same phantom-logout that unit 018 was opened to fix.

Deliberately NOT fixed here. The real fix is two-sided: the client keys on
`res.redirected` + pathname, AND the endpoint must fail as JSON — and the
endpoint half is `app/routes.py`, which this unit is contractually barred from
touching. Fixing only the client half would leave a raw 500 rendering as
"Server error" with no logging change, which is better but still half the fix.

File as a followup issue.

### TODO — a `currency` Jinja filter

15 in-template `"{:,.2f}".format(...)` call sites exist because registering a
filter means editing `app/__init__.py` (the app registers no template filters at
all), which the coordination contract barred. One definition beats 15 call sites;
worth doing once `2026-08-24-merchant-group-index` has merged and the contract
lapses. Low priority — the current form is correct, just repetitive.

## Review triage 2026-08-24 (code quality pass, 8 findings)

Seven fixed, one rejected.

- **#1 HIGH — `--text-subtle` failed WCAG AA. FIXED, by deleting the tier.**
  Measured it rather than trusting the report: `#98a2b3` gave **2.58:1** on
  `--surface` and **2.34:1** on `--surface-2`, against a 4.5:1 AA floor — and it
  was applied to *every table header on every page*, the eyebrow labels, and the
  week-divider rows. A real regression: the Bootstrap `.text-muted` it replaced
  measured 4.69:1.
  The arithmetic then killed the tier outright. Clearing 4.5:1 on `--surface-2`
  needs a value no lighter than `--text-muted` (`#667085` = 4.51:1), so a third,
  lighter text tier could only ever have existed by failing contrast. Deleted
  `--text-subtle` and the `.subtle` class; the 10 call sites now use `.muted`.
  Two text tiers, both AA-clean. The token block records why, so nobody
  reintroduces a "subtle" grey for small text.
- **#2 MEDIUM — `.retry-btn` was a dead rule. FIXED.** `chat.css` defined it to
  replace Bootstrap's `ms-2` margin, but `chat.js:115` never applied it, so the
  retry button sat flush against the error text. Exactly the dead-class failure
  mode the earlier sweep was looking for, and it slipped through because the
  class existed in CSS — the sweep checked markup→CSS, not CSS→markup.
- **#3 MEDIUM — `/` lost its only heading. FIXED.** The rewrite turned
  `<h2>Spending · …</h2>` into a `<div class="eyebrow">`. Every other page gained
  an `<h1>`; the busiest one silently lost heading navigation. Now an `<h1>`
  carrying the same `.eyebrow` styling.
- **#4 MEDIUM — budget tiles and chart bars had no keyboard path. FIXED,
  deliberately widening the proposal.** Pre-existing rather than a regression —
  but these elements were rewritten line-for-line in this change, and carrying a
  keyboard trap forward through a full rewrite is how it becomes permanent. Added
  `role="button" tabindex="0"` + `aria-label`, and one delegated `keydown`
  listener translating Enter/Space into a click (a div, unlike a button, does not
  synthesise one). This is the single exception to the proposal's "changes no
  behaviour" claim: additive keyboard activation, no existing path altered.
- **#5/#6 LOW — dead `.gap-4`, dead `.text-accent`, unconsumed `--shadow-md`.
  FIXED** (deleted).
- **#8 LOW — `.btn-warn:hover` at 4.17:1. FIXED.** Darkened `--warn`
  `#b54708` → `#93370d`: 5.78:1 on the hover background, 7.21:1 on the resting
  one.
- **#7 LOW — "delete the redundant `.table td.empty`". REJECTED — the finding is
  wrong, and wrong in exactly the way #1's sibling bug was.** It claims bare
  `.empty` already produces the result. It does not: `.table td` sets padding at
  specificity (0,1,1) and beats `.empty` at (0,1,0), which is precisely why the
  qualified rule was added. Both rules are load-bearing and neither is redundant
  — `.empty` also styles a non-table `<div>` in `settings.html`. Deleting it
  would have silently restored cramped padding on every empty-state table cell.
  Verified by reading the cascade, not by re-running the suite: no test can see
  this.
