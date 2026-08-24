# Proposal: ui-design-system

**Date**: 2026-08-24
**Status**: Draft

## Goal

Replace stock Bootstrap 5 with a purpose-built, hand-authored design system so the
app looks designed rather than defaulted — a refined light theme plus a real dark
theme that follows the OS — while changing no behaviour, no route, and no template
context.

## Why

The UI is Bootstrap 5.3.0 from a CDN plus two lines of inline override in
`base.html`. There is no type scale, no spacing rhythm, no palette, no dark mode;
tables sit at default density and money renders in proportional figures. The look
is entirely a CSS-and-markup problem — no framework migration is needed, and a
React rewrite would cost weeks while changing none of the things that actually
make it look plain.

Three concrete defects motivate the work beyond taste:

- **Money is unreadable at scale.** Templates format with `"%.2f"`, so a real
  account renders `$615966.75`. `app/notifications.py` already formats the same
  figures as `$615,966.75` (`:,.2f`, lines 80-82/100/113), so the web page is the
  inconsistent surface, not the SMS digest.
- **No dark mode**, on an app whose primary use is a daily balance check.
- **Bootstrap's defaults carry no information design** — every badge is the same
  weight, amounts are not tabular, and hierarchy comes from Bootstrap's `h4`/`h6`
  rather than from the data's actual importance.

## Approach

A hand-authored stylesheet at `app/static/app.css`, driven by CSS custom
properties, replacing the Bootstrap CDN link. Both themes are defined as token
sets; dark activates via `prefers-color-scheme`. Every template is rewritten
against the new vocabulary.

**Chosen over the alternatives:**

- **Tailwind + a build step** — rejected. It needs a Node stage or the standalone
  binary added to a `Dockerfile` that is currently a clean `pip install`, and it
  needs a custom theme purely so `text-danger`/`text-success` survive (they are
  not stock Tailwind utilities). The Play CDN is production-discouraged and would
  re-add the CDN-script pattern this change exists to remove. All toolchain cost,
  no visual benefit over hand-authored CSS at this size.
- **Theming Bootstrap in place** — rejected. Overriding Bootstrap's variables
  keeps its component geometry and still ships the framework; it gets perhaps 60%
  of the way and leaves the defaults visible.

**Hard constraint — zero `.py` file changes.** A concurrent session
(`2026-08-24-merchant-group-index`) owns `app/routes.py`, `app/models.py`,
`app/sync.py`, `app/subscriptions.py`, `app/bills.py` and a migration. Both
sessions have agreed a disjoint file contract: it does not touch
`app/templates/*` or `app/static/*`; this unit touches nothing else.

Two consequences follow from that constraint and are deliberate, not incidental:

1. `app/routes.py:261` emits `'amount_class': 'text-danger' | 'text-success'` into
   the `/api/transactions` JSON, which the infinite-scroll JS applies verbatim to
   appended rows. Those two class names therefore stay live in the new stylesheet
   rather than being renamed.
2. The app registers **no** Jinja filters anywhere, so adding a `currency` filter
   would mean editing `app/__init__.py`. Currency grouping is done in-template
   with `"{:,.2f}".format(...)` across the 15 format sites instead. One
   definition would be the better long-term design; it is deferred rather than
   taken, because breaking a live coordination contract costs more than 15 call
   sites.

`app/notifications.py` is explicitly out of bounds: its message text is filed with
the carrier for A2P 10DLC, and changing it would force
`docs/twilio-a2p-campaign-resubmission.md` to be re-filed while brand
registration is still settling (knowledge 022).

### Scope

All 7 templates, `app/static/chat.css`, and the inline `<script>` blocks' class
strings. Single unit, not decomposed: removing Bootstrap is atomic — a partial
migration leaves two stylesheets fighting and every unconverted page visibly
broken, so there is no coherent intermediate state to ship.

The design system must fully replace Bootstrap's semantic vocabulary, not lightly
restyle it: the grid (`row-cols-*`), cards, navbar, list-groups, badges in four
variants, alerts, progress bars, form controls, and ~6 button variants — plus the
four hard-coded class strings inside `index.html`'s inline JS (lines 226-241).

## Success criteria

1. **Bootstrap is gone.** No `cdn.jsdelivr.net/npm/bootstrap` reference in any
   template. The only remaining external origins are `cdn.plaid.com` (Link) and
   the `marked` CDN in `chat.html`.
2. **The suite passes.** These assertions encode semantic *contracts* and must
   pass untouched: `b'Vested' not in res.data`, `b'Unvested' not in res.data`,
   `b'Due ' not in res.data`, `b'Overdue' not in res.data`, `b'min $' not in
   res.data`, `'—'.encode() in res.data`, `b'>Transactions<'`. Currency literals
   (`b'$12345.67'`, `b'$8900.00'`, `b'$1234.56'`, `b'$432.10'`) are *formatting
   snapshots*, not contracts — they may be updated to the grouped form, and each
   such edit is justified in the diff. No other test may be edited.
3. **Zero Python changed.** `git diff --name-only main...HEAD -- '*.py'` is empty.
4. **Null is not zero.** A missing balance renders `—`, never `$0.00`. The
   liability and vested/unvested rows stay gated on `is not none`, so an account
   with no vesting schedule shows no vested row at all (knowledge 021).
5. **Lapsed is not low-priority.** An inactive subscription/bill still renders
   dimmed with a neutral "Inactive" badge, never the red "Unpaid" treatment
   (knowledge 005).
6. **Session-expiry detection is untouched.** In `sendDigest`, the
   `res.redirected` + `/login` pathname check stays the expiry signal and
   Content-Type stays a parse guard only; the diff for that function shows class
   strings changing and nothing else (knowledge 012/019).
7. **Money is grouped and tabular.** All amounts use `{:,.2f}` / `{:,.0f}`,
   matching `notifications.py`, and render with `font-variant-numeric:
   tabular-nums`.
8. **Both themes render.** Light is the default; dark activates on
   `prefers-color-scheme: dark`. Every page is legible in both.
9. **Responsive.** All 7 pages render at 375px and 1440px with no horizontal
   overflow. The navbar needs a from-scratch small-screen answer — it currently
   has no collapse behaviour to inherit.

## Open Questions

None blocking. The user chose the visual direction (refined light + OS-following
dark), the CSS approach (hand-authored), and the review cadence (all 7 pages in
one pass, reviewed at the PR) at intake.
