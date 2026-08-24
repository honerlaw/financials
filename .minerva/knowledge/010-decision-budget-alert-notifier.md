# Weekly-budget SMS alerts: notifier design

**Date**: 2026-07-05
**Type**: decision
**Summary**: Weekly-budget SMS alerts fire from the sync path — per-recipient dedup via BudgetAlert, in-process lock + unique constraint for no-double-send (relies on --workers 1), record-after-send retry, soft-disabled unless all Twilio config is set
**Context**: .minerva/work/012-weekly-budget-sms-alerts

<!-- superseded-by: 016 -->
> **Superseded by [[016-decision-daily-digest-notifier]]** (2026-08-08)

## Context

Work unit 012 added proactive SMS alerts on top of the existing weekly-budget
tracker ([[008-decision-dashboard-spend-and-weekly-budget]]). After each sync,
each configured recipient is texted once per Sun–Sat week for every newly-crossed
50/75/100% threshold of the current week's household spend against the $1,000
`WEEKLY_BUDGET`. The logic lives in `app/notifications.py` (pure `newly_crossed`,
the `TwilioSender` SDK wrapper, and the `send_budget_alerts` shell), with
`spending.week_spend` supplying the current-week total and a `BudgetAlert` model
providing dedup.

> **What of this still applies.** The threshold cadence below is gone —
> `newly_crossed`, `THRESHOLDS` and the `BudgetAlert` model were removed in unit
> 016 in favour of one daily 7am digest. The *shape* of the notifier survives it:
> soft-disable on missing config, per-recipient dedup, record-after-send, the
> module lock plus unique-constraint backstop, and the non-fatal sync hook. Read
> decisions 2, 3, 4 and 5 as live rationale; read decision 1 and the spend
> semantics as history.

## Decisions

1. **Fires from the sync path, every sync.** `send_budget_alerts` is hooked at
   the end of `sync_all_institutions()` via `_send_budget_alerts_safe`, so it
   evaluates on the 7am cron AND on the background-thread sync that `/api/sync`
   kicks off when the dashboard's "Sync now" button is pressed — near-real-time,
   not once-a-day. (Originally written as "on every page load", which was never
   true; see
   [[029-pattern-only-the-call-site-is-authoritative-for-runtime-behaviour]].) The hook is
   **non-fatal**: the import *and* the call sit inside one `try/except` logging
   via `current_app.logger` (never `SyncLog.error`), mirroring the
   `_refresh_balances` contract ([[007-decision-plaid-reconnect-update-mode]]).
   A notifier failure — including an import-time failure — never aborts a sync.

2. **Per-recipient dedup grain.** `BudgetAlert` is unique on
   `(week_start, threshold, recipient)`, not `(week_start, threshold)`. One
   recipient's send failure therefore never blocks the other's alert and never
   produces a duplicate. A row is loaded per recipient to compute the
   already-sent set fed to `newly_crossed`.

3. **No-double-send = in-process lock + unique constraint, and it depends on a
   single worker.** The whole body of `send_budget_alerts` runs under a
   module-level `threading.Lock`, fully serializing check→send→record across the
   concurrent sync threads. This is correct **only because the app runs one
   gunicorn worker** (`entrypoint.sh: --workers 1`) — an invariant the in-process
   APScheduler already requires. The DB unique constraint (+ a caught
   `IntegrityError`) is the cross-process backstop: it prevents a duplicate
   *row*, but cannot un-send a duplicate *SMS* if the single-worker invariant is
   ever broken. **Known gap:** that invariant is not runtime-enforced (see
   followups) — bumping worker count silently reopens cross-process double-sends.

4. **Record-after-send, deliberately.** The `BudgetAlert` row is written only
   after a successful `sender.send`, so a failed send leaves nothing recorded and
   is retried next sync. The chosen failure mode: if the *commit* fails after a
   successful send (rare — dropped connection etc.), the code rolls back, logs,
   and continues, accepting a possible duplicate text on retry. This was chosen
   over pre-claiming the row before sending, because a claim-then-failed-send
   would *silently drop* a milestone — and never missing a milestone is the
   feature's whole point. Duplicate > miss, for a budget alert.

5. **Soft-disabled unless fully configured.** The feature is a clean no-op unless
   all four of `TWILIO_ACCOUNT_SID` / `TWILIO_AUTH_TOKEN` / `TWILIO_FROM_NUMBER` /
   `BUDGET_ALERT_RECIPIENTS` are set. Missing config does **not** hard-fail
   startup (unlike `SECRET_KEY`/`APP_PASSWORD`). This lets the code ship to
   production inert and be verified against real spend before any number is
   wired up. The `twilio` import is lazy inside `TwilioSender`, so it is never
   imported when the feature is off (or in tests, which inject a fake sender).

## Spend semantics

`week_spend(transactions, today)` reuses `is_spend` / `week_start`, so the alert
total shares the dashboard's spend definition exactly (positive amounts,
excluding `TRANSFER`/`LOAN_PAYMENTS`, Sun–Sat weeks). It is a **household total**
— no institution filter — unlike the dashboard section, which is filterable.
`pct = int(spent / WEEKLY_BUDGET * 100)`, matching the tracker's truncation.

## Known limitations / operational

- **"Sent" ≠ "delivered".** The row is written on Twilio API-accept. US A2P 10DLC
  registration of the FROM number is an operational prerequisite; an unregistered
  number is silently carrier-filtered while every log/test still reads "sent".
- **Headless by design** — no in-app UI for alert history or a toggle.
- `$1,000` weekly budget and the 50/75/100 thresholds are hardcoded constants.

## Related

- [[008-decision-dashboard-spend-and-weekly-budget]] — builds on
  the weekly-budget math and spend definition this reuses (`is_spend`, `week_start`, `WEEKLY_BUDGET`).
- [[002-decision-plaid-balance-refresh-via-dedicated-endpoint]] — see also
  the sibling non-fatal side-effect (`_refresh_balances`) inside the sync path that this hook mirrors.
- [[004-pattern-seed-relative-dates-in-time-sensitive-tests]] — see also
  why `week_spend` and `newly_crossed` take the reference date / state as parameters.
- [[011-decision-doppler-hybrid-config]] — see also
- [[016-decision-daily-digest-notifier]] — superseded by
- [[018-decision-on-demand-digest-trigger]] — see also
- [[020-pattern-injected-fakes-hide-construction-failures]] — see also
