# Followups — 016-daily-balance-digest

## No catch-up if the container is down at 7am

The digest is dispatched only by `run_daily_sync`, which only the APScheduler
cron calls. APScheduler does not replay a cron job whose time passed before the
process started, so a deploy or restart spanning 07:00 silently skips that day's
digest — nothing logs, and the next dispatch is 24 hours later.

Options for a future work unit:
- Give the job a misfire grace period (`misfire_grace_time`) so a scheduler that
  starts slightly late still runs it.
- Add a bounded catch-up on the page-load sync path: send if no `DailyDigest`
  row exists for today AND the local hour is inside a morning window (say 7–11),
  so a late text is still a morning text.
- Alert on absence — a heartbeat that notices no digest row was written by noon.

Severity is low: the invariant only breaks on a restart that straddles 7am.

_Source: 016 review triage (F4), 2026-08-08._

## Digest body is UCS-2, doubling segment count

`—`, `·` and `••` in the message push it off the GSM-7 alphabet, so segments are
70 characters instead of 160 — a ~250-character digest bills roughly 4 segments
rather than 2. Swapping to ASCII (`-`, `|`, `x`) would halve it. Kept as-is for
continuity with the unit-012 message voice; revisit only if Twilio spend ever
matters (it is pennies a month at one recipient).

_Source: 016 review triage (F3), 2026-08-08._

## No cap on digest length

Twilio rejects a body over 1600 characters (error 21617). Each account line runs
~45 characters, so roughly 30+ linked accounts would hit the ceiling and the
send would fail for every recipient — logged and retried, but never delivered.
A truncating tail (`…and N more`) would bound it. Not built: the household has
three institutions.

_Source: 016 review triage (F5), 2026-08-08._
