# Proposal: daily-balance-digest

**Date**: 2026-08-08
**Status**: Shipped (2026-08-08)

## Goal

Replace the threshold-triggered weekly-budget SMS with a **single daily digest
text sent at 7am local time**, carrying both where the week's budget stands
(spent / cap / percent / remaining-or-over) and the **current balance of every
linked account**.

## Why

The notifier shipped in unit 012 only texts when a 50/75/100% weekly-budget
threshold is *newly crossed*. Two consequences the user does not want:

- **Silence is common.** A week under $500 of spend produces zero texts. There
  is no "where do we stand" signal unless spending is already high.
- **Timing is unpredictable.** The send happens on whichever sync first
  observes the crossing — the 7am cron, or any of the background syncs
  `/api/sync` fires on every dashboard page load.

The user's stated intent: *"we don't really care about crossing the budget
threshold. I just want to be notified everyday of where we stand"* — one
predictable morning text, every day, with budget status **and** account
balances.

Account balances are already refreshed live from Plaid's `/accounts/balance/get`
on every sync ([[002-decision-plaid-balance-refresh-via-dedicated-endpoint]]),
so `Account.current_balance` is authoritative as of the last sync — and the
digest is dispatched immediately after the 7am sync, making it as fresh as the
data gets.

## Approach (as shipped)

### 1. Notifier rewrite — `app/notifications.py`

`newly_crossed` / `THRESHOLDS` / `send_budget_alerts` are **removed**, replaced
by `send_daily_digest(session, today, config, sender=None)`. The pure
message-building helpers stay pure and unit-tested; the Twilio send and the
`DailyDigest` write remain the impure shell.

Message shape (one text; the punctuation makes it UCS-2, so ~4 segments):

```
Good morning — Sat Aug 8

Budget: $750 of $1,000 (75%) — $250 left
Week of Aug 2

Balances
American Express · Platinum Card ••1004: $2,143.19
Citi · Double Cash ••8821: $612.40 (reconnect needed)
Truist · Checking ••3390: $4,880.02
```

- Over budget flips the tail to `— $240 OVER` and the percent reads past 100
  (e.g. `124%`), satisfying "still text the budget caps and such and percent
  over budget".
- Balances are grouped `Institution · Account ••mask` and ordered by
  institution then account name — the same ordering the dashboard uses.
- Balance values render exactly as the dashboard renders them (raw
  `current_balance`, no sign flipping) so the text and the UI never disagree.
  A null balance renders `—`.
- Accounts with no balance still appear, so a newly-linked account is visible.
- An account whose institution is not `status='active'` gets a
  `(reconnect needed)` suffix. `sync_all_institutions` skips those Items, so
  their balance is frozen at the last good sync; the dashboard can show that
  number safely next to a reconnect banner, an SMS cannot. (Added during review
  — finding F1.)

### 2. Dedup model — `DailyDigest` + migration

New `daily_digests` table, unique on `(sent_date, recipient)`: each recipient
gets at most one digest per day. Written **after** a successful send, so a
failed send is retried by the next dispatch — the record-after-send tradeoff
from [[010-decision-budget-alert-notifier]] carries over unchanged (a duplicate
text beats a silently-dropped one).

`budget_alerts` is dropped in the same migration. It is a send-log for a
feature being retired, has no reader anywhere in the app (the notifier was
"headless by design"), and the migration's `downgrade` recreates it.

### 3. Dispatch moves off the page-load sync path — `app/sync.py` + `wsgi.py`

The `_send_budget_alerts_safe()` hook is **removed from
`sync_all_institutions()`**. Page-load syncs must not text.

A new `run_daily_sync()` in `app/sync.py` runs the sync and then dispatches the
digest through a non-fatal wrapper (`_send_daily_digest_safe`), preserving the
contract that a notifier failure — import-time included — never aborts a sync.
The 7am APScheduler cron calls `run_daily_sync` instead of
`sync_all_institutions`.

The scheduler wiring itself moved out of `wsgi.py` into
`app/scheduler.py::start_scheduler(app)`. Importing `wsgi` starts a real
scheduler as a side effect, which left the "fires at 7am in the right zone"
behaviour untestable; `tests/test_scheduler.py` now pins the hour, the trigger
timezone, and that the scheduled callable is the notifying path. `wsgi.py` is
reduced to `create_app()` + `start_scheduler(app)`.

### 4. 7am means 7am here, not 7am UTC — `APP_TIMEZONE`

The container sets no `TZ`, so the existing `hour=7` cron currently fires at
**07:00 UTC = 03:00 America/New_York**. Shipping the digest on that trigger
would text at 3am. A new `APP_TIMEZONE` config (default `America/New_York`,
matching this repo's commit offsets) is passed as the cron job's timezone, and
supplies the digest's local `today`. Wrong-guess recovery is a config change,
not a code change.

Side effect, intended: the daily *sync* also moves from 07:00 UTC to 07:00 ET.
`/api/sync` on page load remains the primary sync trigger, so this is a
backstop shift, not a data-freshness regression.

Two implementation details worth keeping: the zone is handed to APScheduler as
an IANA **name** (`str(ZoneInfo)`) rather than a `tzinfo`, because
`requirements.txt` pins only `APScheduler>=3.10.0` and older 3.x rejected
non-pytz tzinfo objects; and `tzdata` was added to requirements, since
`python:3.12-slim` is not guaranteed to ship the system IANA database and a
missing tzdb would silently route every lookup through the fallback.

### 5. Config surface

`BUDGET_ALERT_RECIPIENTS` **keeps its name**. Secrets live in the shared
Doppler project `onerlaw`, which spans several repos
([[011-decision-doppler-hybrid-config]]); renaming a var there is shared-state
churn with a sibling-repo blast radius, for zero functional gain. `.env.example`
comments are updated to describe the digest instead of threshold alerts.

Soft-disable is unchanged: no recipients, or any missing Twilio credential, and
the whole feature is an inert no-op.

### Rejected alternatives

- **Keep threshold alerts and add a digest alongside.** The user explicitly
  does not care about crossings; keeping both means two code paths, two dedup
  tables, and more texts than asked for.
- **Dispatch the digest from the shared sync path, gated on "not sent today and
  local hour ≥ 7".** Survives a missed cron, but a page load at 9pm then sends
  the "good morning" text at 9pm. Predictable timing was the ask.

## Success criteria

1. One SMS per recipient per calendar day, dispatched right after the 7am sync,
   containing: week-to-date spend, the weekly cap, percent of cap, and
   remaining-or-over.
2. That same SMS lists every linked account with its current balance, grouped by
   institution, matching dashboard values and ordering.
3. Threshold alerting is gone: no `newly_crossed`, no `THRESHOLDS`, no
   `BudgetAlert`, and no code path that can send more than one text per day.
4. A second dispatch on the same day is a no-op; a failed send leaves no row and
   is retried on the next dispatch.
5. The 7am trigger resolves in `APP_TIMEZONE` (default `America/New_York`), not
   UTC.
6. Page-load syncs (`/api/sync`) never send a text.
7. The feature stays soft-disabled without full Twilio config, and a digest
   failure never aborts a sync.
8. `pytest` passes, with new coverage for: digest body (under/over budget), the
   per-day dedup, null balances, no-accounts, and the cron wiring.

## Open Questions

None blocking. `APP_TIMEZONE`'s default is inferred from commit offsets
(`-0400`); if it is wrong, it is a one-line config fix.

## Verification

`pytest`: 209 passed. Migration `d5a1c9e37b48` round-tripped by hand — the full
chain cannot replay on SQLite (see
[[016-pattern-migration-chain-is-postgres-only]]), so it was stamped, upgraded
and downgraded in isolation. Digest bodies were rendered end-to-end against a
seeded 3-institution / 4-account database, under and over budget.

Deferred, in `followups.md`: no catch-up for a 7am the container sleeps through
(F4), UCS-2 segment count (F3), no 1600-character cap (F5).
