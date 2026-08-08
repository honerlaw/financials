# Daily digest SMS: one morning text, not threshold alerts

**Date**: 2026-08-08
**Type**: decision
**Summary**: Threshold budget alerts replaced by one 7am daily digest (budget status + every account balance) — dispatched only from run_daily_sync so page-load syncs never text, deduped per (sent_date, recipient), and scheduled in APP_TIMEZONE because the container is UTC.
**Context**: .minerva/work/016-daily-balance-digest

## Context

Unit 012 shipped SMS that fired only when a 50/75/100% weekly-budget threshold
was newly crossed ([[010-decision-budget-alert-notifier]]). Two properties made
it the wrong shape for what the user actually wanted: a week under 50% of budget
produced **zero** texts, and the send landed whenever a sync happened to observe
the crossing — including the background sync `/api/sync` fires on every
dashboard page load. The ask was a predictable "where do we stand" text every
morning, carrying account balances as well as budget status.

## Decisions

1. **Cadence is daily, not threshold-driven.** `newly_crossed`, `THRESHOLDS` and
   the `BudgetAlert` model are gone. `send_daily_digest` builds one message per
   day containing the week's spend, the `WEEKLY_BUDGET` cap, percent of cap
   (uncapped — 124% reads as `124%`), remaining-or-`OVER`, and one line per
   account. Nothing suppresses a quiet week; that silence was the bug.

2. **Only the 7am job notifies.** `app/sync.py` now separates
   `sync_all_institutions()` (pure sync, called by `/api/sync` on every page
   load) from `run_daily_sync()` (sync, then `_send_daily_digest_safe()`). The
   APScheduler cron calls the latter, so the digest lands at a predictable hour
   instead of whenever the dashboard is next opened, and syncing first makes the
   balances as fresh as Plaid allows. The non-fatal wrapper contract is
   unchanged — an import-time or runtime failure in the notifier never aborts a
   sync ([[007-decision-plaid-reconnect-update-mode]]).

3. **"7am" needs an explicit timezone — the container has none.** No `TZ` is set
   in the image, so the pre-existing `hour=7` cron was firing at **07:00 UTC =
   03:00 America/New_York**. `app/localtime.py` resolves `APP_TIMEZONE`
   (default `America/New_York`) and supplies both the scheduler's timezone and
   the digest's notion of "today". A bad zone name warns and falls back to the
   default rather than to UTC — UTC is precisely the wrong answer for a
   wall-clock job. Side effect, accepted: the daily *sync* moved to 07:00 ET too.
   `tzdata` is now a requirement because `python:3.12-slim` is not guaranteed to
   carry the system IANA database.

4. **Dedup grain is `(sent_date, recipient)`.** `DailyDigest` replaces
   `BudgetAlert`; migration `d5a1c9e37b48` creates it and **drops**
   `budget_alerts` (a send-log for a retired feature with no reader in the app;
   `downgrade` recreates the table but not its rows). Record-after-send is
   retained from unit 012 verbatim: the row is written only after a successful
   Twilio send, so a failed send is retried next dispatch, and a commit failure
   after a successful send rolls back and accepts a possible duplicate. For a
   daily digest as for a budget alert, duplicate > miss.

5. **Balances from a non-syncing bank are labelled, not silently shown.**
   `sync_all_institutions` only syncs `status='active'` institutions, so an Item
   in `login_required` keeps its last-good `current_balance` forever. The
   dashboard can render a stale number safely because a reconnect banner sits
   beside it ([[007-decision-plaid-reconnect-update-mode]]); an SMS has no such
   context, so those lines get a `(reconnect needed)` suffix. Values themselves
   are printed exactly as the dashboard prints them — raw `current_balance`, no
   sign flipping — so the text and the UI can never disagree.

6. **`BUDGET_ALERT_RECIPIENTS` keeps its name** despite now being digest
   recipients. The secret lives in the shared Doppler project `onerlaw`, which
   spans several repos ([[011-decision-doppler-hybrid-config]]); renaming there
   is cross-repo churn for zero functional gain.

## Known limitations / operational

- **No catch-up.** Dispatch happens only from the 7am job. A container down at
  07:00 (a deploy, a restart) silently skips that day — the in-process scheduler
  does not run missed jobs on start. See the unit's `followups.md`.
- **UCS-2 billing.** `—`, `·` and `••` in the body push it off GSM-7, so a
  ~250-char digest bills ~4 segments rather than 2. Pennies a month, kept for
  continuity with the unit-012 message voice.
- **No length cap.** Twilio rejects bodies over 1600 characters; roughly 30+
  accounts would reach that. Not a concern at current scale.
- **"Sent" ≠ "delivered"** still holds — the row records Twilio API-accept, and
  A2P 10DLC registration of the FROM number remains an operational prerequisite.
- Single-worker invariant unchanged: the module lock is correct only under
  `gunicorn --workers 1`, with the unique constraint as cross-process backstop.

## Related

- [[010-decision-budget-alert-notifier]] — supersedes
  the threshold design; its dedup and failure-mode reasoning carry over, its cadence does not.
- [[008-decision-dashboard-spend-and-weekly-budget]] — builds on
  the spend definition and `WEEKLY_BUDGET` the digest reports against.
- [[007-decision-plaid-reconnect-update-mode]] — builds on
  both the non-fatal side-effect contract and the reconnect state that makes a balance stale.
- [[002-decision-plaid-balance-refresh-via-dedicated-endpoint]] — see also
  why `Account.current_balance` is authoritative only as of the last sync.
- [[011-decision-doppler-hybrid-config]] — see also
  why the recipients variable was not renamed.
- [[017-pattern-migration-chain-is-postgres-only]] — see also
  how this unit's migration had to be verified.
