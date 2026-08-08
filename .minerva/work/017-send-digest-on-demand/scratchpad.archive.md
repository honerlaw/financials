# Scratchpad — 017-send-digest-on-demand

## Quick decisions 2026-08-08
- [decided] scope: single work unit — one endpoint, one helper, one button; nothing independently shippable
- [decided] approach: separate `send_digest_now` reusing 016's pure builders, rather than a `force=True` flag on `send_daily_digest` — keeps the scheduled path's contract untouched
- [decided] dedup semantics: manual send reads and writes NO `DailyDigest` row. Rejected writing one (a press at 6am would silently cancel the 7am text — an invisible second effect for a button labelled "send now"). Accepted edge: pressing at 06:55 yields two texts
- [decided] "instead" in the request reads as "triggered by me instead of the clock", not "replace the 7am schedule" — the schedule shipped hours ago and the user was happy with it; this is additive
- [decided] button lives in the dashboard Spending card header, not Settings — the digest's content (budget + balances) is dashboard content, and the user implied frequent casual use; Settings holds infrequent operational actions
- [decided] synchronous endpoint, not the background-thread pattern `/api/sync` uses — the caller wants the outcome, and the Twilio call is already bounded at 10s
- [decided] must follow [[012-pattern-fetch-content-type-session-detection]] in the button's fetch — session expiry on a `@login_required` route returns HTML 200, not a non-ok status

## Notes
- Rendered the dashboard header end-to-end (test client, configured + unconfigured) rather than
  trusting the assertions alone — button markup, title, and disabled state all correct.

## Review triage 2026-08-08
Inline review (minerva spec/knowledge audit + code review of `git diff main...HEAD`). No PR yet,
so no `code-review:code-review` delegation.

- **F1 (medium) → FIX.** `routes._sms_configured()` hand-reimplemented the soft-disable gate,
  approximating `_recipients()` with a bare `.strip()` on the raw string. The two could disagree:
  `BUDGET_ALERT_RECIPIENTS=","` is truthy after strip (button renders enabled) but parses to zero
  recipients (press → 400). Replaced with `notifications.is_configured(config)` as the single
  source of truth, built from the same `_recipients` the send paths use plus a new
  `_has_credentials` helper that `_sender_from_config` now shares. `is_configured` constructs
  nothing, so the deliberate lazy `twilio` import ([[010-decision-budget-alert-notifier]]) is
  preserved on page loads. Regression test:
  `test_button_disabled_for_recipients_that_parse_to_nothing`.
- **F2 (low) → accepted, documented.** The endpoint is synchronous and the app runs
  `--workers 1`, so a hung Twilio blocks the single worker for up to 10s per recipient (the
  `TwilioSender` timeout), bounded overall by gunicorn's 120s. Not worth a background thread:
  reporting the outcome is the whole point of the button, and the person waiting is the one who
  pressed it. Noted as a limitation rather than fixed.
- **Spec fidelity: clean.** All seven success criteria met with test evidence; no divergence from
  the written approach.
- **Knowledge compliance: clean.** The button's fetch checks Content-Type before parsing
  ([[012-pattern-fetch-content-type-session-detection]]); the scheduled path's contract from
  [[016-decision-daily-digest-notifier]] is untouched — `send_daily_digest` is not modified at
  all, and the manual path shares only pure builders; the lazy twilio import from
  [[010-decision-budget-alert-notifier]] survives the `_sender_from_config` refactor.
