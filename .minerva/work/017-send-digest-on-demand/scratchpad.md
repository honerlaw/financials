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
