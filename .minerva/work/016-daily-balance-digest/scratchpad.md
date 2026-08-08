# Scratchpad — 016-daily-balance-digest

## Quick decisions 2026-08-08
- [escalated to user] cadence: threshold-appended vs. new daily digest vs. digest-replaces-alerts — no dominant reading of "change the notifications"; user chose digest REPLACES threshold alerts, 7am daily, keeping cap/percent/over-budget in the body
- [decided] scope: single work unit — one coherent feature (notifier rewrite + dedup model + dispatch move + tz config); no independently shippable sub-unit
- [decided] approach: rewrite `app/notifications.py` around `send_daily_digest` + `DailyDigest(sent_date, recipient)`, dispatch from a new `run_daily_sync()` called by the 7am cron. Rejected: (a) keep thresholds and add a digest alongside — user doesn't want crossings, two dedup tables; (b) dispatch from the shared sync path gated on hour≥7 — a 9pm page load would send the "good morning" text at 9pm
- [decided] drop `budget_alerts` in the migration rather than leave it dead — send-log for a retired feature, no reader in the app, `downgrade` recreates it
- [decided] keep the `BUDGET_ALERT_RECIPIENTS` name — Doppler project `onerlaw` is shared across repos (011 + doppler.yaml warning); renaming is shared-state churn for zero functional gain
- [decided] `APP_TIMEZONE` default `America/New_York` from this repo's commit offsets (-0400) — container sets no TZ, so today's `hour=7` cron is 3am ET; wrong guess is a config fix, not a code fix
- [decided] balances render raw `current_balance` with no sign flipping — matches `index.html` exactly so text and dashboard never disagree

## Notes
