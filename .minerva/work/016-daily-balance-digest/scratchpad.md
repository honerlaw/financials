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
- Extracted the scheduler wiring out of `wsgi.py` into `app/scheduler.py::start_scheduler(app)`.
  Not a divergence from the approach (the 7am cron still calls `run_daily_sync`) — importing
  `wsgi` starts a real scheduler as an import side effect, so success criterion 5 ("7am resolves
  in APP_TIMEZONE") was otherwise untestable. `tests/test_scheduler.py` now pins the hour, the
  trigger timezone, and that the scheduled callable is the notifying path.
- Passed the timezone to APScheduler as an IANA **name** (`str(ZoneInfo)`) rather than the
  tzinfo object. 3.11.2 (installed) accepts `ZoneInfo`, but `requirements.txt` pins only
  `>=3.10.0`, and older 3.x rejected non-pytz tzinfo with `TypeError`. `app_timezone()` has
  already validated/fallen back by then, so nothing is lost.
- Added `tzdata` to requirements: `python:3.12-slim` is not guaranteed to carry system IANA data,
  and a missing tzdb would silently push `app_timezone()` onto its fallback path in production.
- Migration verified by hand: the full SQLite chain can't run (pre-existing Postgres-only `GRANT`
  in `00a2889ed2af`), so `d5a1c9e37b48` was exercised in isolation — stamp `c4e8b2f6a1d9`, create
  `budget_alerts`, upgrade (→ `daily_digests` + unique index, `budget_alerts` gone), downgrade
  (→ inverse). Round-trips clean.
- Rendered digests end-to-end (4 accounts / 3 institutions): 248 chars under budget, 251 over.
  Body uses `—`, `·`, `••`, so it encodes as UCS-2 (70 chars/segment) — ~4 segments, a few cents
  a month. Kept for continuity with the unit-012 message voice; noted as a followup, not a bug.

## Review triage 2026-08-08
Inline review (minerva spec/knowledge audit + code review of `git diff main...HEAD`).
No PR existed yet, so no `code-review:code-review` delegation.

- **F1 (medium) → FIX.** `_account_balances` joined every institution regardless of
  `Institution.status`, but `sync_all_institutions` only syncs `status='active'` — so a bank
  in `login_required` keeps its last-good `current_balance` indefinitely and the digest would
  have texted a frozen number as if current. The dashboard gets away with this because it
  renders a reconnect banner beside the card; an SMS has no such context. Fixed: the query
  carries `Institution.status`, and `account_line(..., stale=True)` appends
  `(reconnect needed)`. Covered by `test_digest_flags_accounts_of_a_bank_needing_reconnect`
  and a pure `account_line` test.
- **F2 (low) → FIX.** `test_unknown_timezone_falls_back_to_default_not_utc` took a `caplog`
  fixture it never used. Now asserts the warning actually names the bad zone.
- **F3 (low) → followups.** `—`, `·`, `••` force UCS-2 (70 chars/segment), so a ~250-char
  digest bills ~4 segments instead of 2.
- **F4 (low) → followups.** No catch-up: the digest is dispatched only by the 7am job, so a
  container down at 7:00 skips that day silently.
- **F5 (low) → followups.** No length cap; Twilio rejects bodies over 1600 chars, which ~30+
  accounts would reach.
- **Spec fidelity: clean.** Every `## Success criteria` item is met by the diff; the only
  structural addition beyond the written approach is `app/scheduler.py`, logged above.
- **Knowledge compliance: clean, with one promote obligation.** The non-fatal-side-effect
  contract from [[007-decision-plaid-reconnect-update-mode]] is preserved by
  `_send_daily_digest_safe`; the single-worker invariant from
  [[010-decision-budget-alert-notifier]] still holds and is still documented. Entry 010 itself
  now describes a retired design and must be superseded during promote.
