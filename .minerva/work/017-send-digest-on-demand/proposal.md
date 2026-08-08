# Proposal: send-digest-on-demand

**Date**: 2026-08-08
**Status**: Draft

## Goal

A button in the app that texts the daily digest **right now** — the same message
the 7am job sends, on demand instead of on the clock.

## Why

Unit 016 made the digest a scheduled, once-a-day artifact
([[016-decision-daily-digest-notifier]]). That is the right default, but it
leaves no way to ask "where do we stand?" at 3pm, and no way to verify the
feature end-to-end without waiting until tomorrow morning. The message content
is already exactly what you'd want on demand — week's spend against the cap plus
every account balance — so this is a second trigger for an existing artifact,
not a new one.

## Approach

### 1. A manual send that ignores the daily dedup — `app/notifications.py`

New `send_digest_now(session, today, config, sender=None)` alongside
`send_daily_digest`. It reuses every existing piece — `_recipients`,
`_sender_from_config`, `_week_spent`, `_account_balances`, `digest_body` — so
the manual text and the 7am text are byte-identical for the same data.

Two deliberate differences from the scheduled path:

- **No `DailyDigest` row is written, and none is read.** A press always sends.
  The button therefore neither suppresses tomorrow's 7am digest nor is
  suppressed by today's. Recording one would mean a press at 6am silently
  cancels the morning text — surprising for something labelled "send now".
- **It reports back.** `send_daily_digest` is a fire-and-forget background
  side-effect that logs failures; a button needs to say what happened, so this
  returns `{'configured': bool, 'sent': [...], 'failed': [...]}` for the route
  to render.

It takes the same module `_send_lock`, so a press can't interleave with a
concurrent 7am dispatch.

Accepted edge: pressing at 06:55 and letting the cron fire at 07:00 yields two
texts. Rare, harmless, and strictly better than the alternative failure mode of
a button that silently does nothing.

### 2. Endpoint — `app/routes.py`

`POST /api/digest/send`, `@login_required`, matching the existing `/api/sync`
and `/api/plaid/*` shape. Synchronous rather than the background-thread pattern
`/api/sync` uses: the caller wants the outcome, and `TwilioSender` already bounds
its HTTP call at 10s.

Responses:
- `200 {'sent': [...], 'failed': [...]}` — at least one text went out
- `400 {'error': ...}` — SMS isn't configured (no recipients, or missing Twilio
  credentials); the soft-disable state surfaces as a real message rather than a
  silent success
- `502 {'error': ...}` — every send failed

### 3. Button — `app/templates/index.html`

A small outline button in the Spending card header, beside the existing
"Weekly budget $1,000" label. The dashboard is where the digest's own content
lives (budget tracker + account cards), which makes it the honest home for
"text me this"; Settings holds infrequent operational actions (resync,
reconnect, disconnect) and would bury it.

The button disables itself while in flight and reports the result inline. Its
`fetch` checks `Content-Type` before parsing, per
[[012-pattern-fetch-content-type-session-detection]] — an expired session
redirects to `/login` rather than throwing on `r.json()`.

The settings route passes nothing new; the dashboard route passes
`sms_configured` so the button renders disabled with a "not configured" hint
when the feature is off, instead of failing only on press.

### Rejected alternatives

- **Write a `DailyDigest` row on manual send.** Makes the button a way to
  "claim" the day, so pressing it early cancels the 7am text. Defensible, but
  it makes a button labelled "send now" have an invisible second effect.
- **Put the button on Settings.** Consistent with the other operational
  buttons, but the digest is dashboard content and the user described frequent,
  casual use.
- **Reuse `send_daily_digest` with a `force=True` flag.** One function with a
  branch on every dedup decision inside it; two small functions sharing pure
  helpers read better and keep the scheduled path's contract untouched.

## Success criteria

1. Pressing the button texts every configured recipient the same message the
   7am job would send for the current data.
2. It works regardless of whether today's scheduled digest already went out,
   and pressing it does not stop tomorrow's.
3. No `DailyDigest` row is created or consumed by a manual send.
4. With SMS unconfigured the button is visibly disabled, and the endpoint
   returns a 400 with a real message rather than a silent success.
5. A per-recipient send failure is reported, not swallowed, and does not stop
   the other recipients.
6. The endpoint is `@login_required`, and its `fetch` handles an expired
   session per the Content-Type pattern.
7. `pytest` passes, with new coverage for the manual-send semantics (dedup
   independence in both directions), the soft-disable path, partial failure,
   and the route's three response shapes.

## Open Questions

None blocking.
