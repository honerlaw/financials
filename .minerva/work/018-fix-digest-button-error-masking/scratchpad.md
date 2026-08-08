# Scratchpad — 018-fix-digest-button-error-masking

## Quick decisions 2026-08-08
- [decided] scope: single unit — one bug with three contributing defects on the same failure path, plus the test gap that let it ship
- [decided] surface the exception message to the client, not a generic string — single-user password-protected app, and naming the failure is the whole point; truncate to 300 chars, full traceback stays in the log
- [decided] redirect on `res.redirected && res.url` ending at /login, not on "not JSON" — refines 012 rather than replacing it (the Content-Type check is still needed to avoid parsing HTML, just not sufficient as an expiry signal)
- [decided] rejected returning 401 JSON from `login_required` for /api/* — cleaner signal but changes a decorator every endpoint shares; disproportionate to this bug and would need every existing fetch audited
- [decided] `app_timezone` degrades to UTC only as a last resort and logs at ERROR — 016 deliberately avoided a silent UTC fallback, so the degradation must be loud
- [decided] the 7am path's silent-failure behaviour is left alone — it is a deliberate non-fatal contract from 012/016; the button now gives an on-demand way to see the same error

## Notes
- Root cause evidence is in this session's minerva:debug report: repro showed 500 + text/html for both placeholder and well-formed AC… SIDs; traceback located the throw at `_sender_from_config`.
- Local venv lacks `twilio` (and `tzdata`) — that specific traceback is a local artifact, not prod's cause. Prod installs from requirements.txt. Prod's actual exception is still unknown; fix 1 is what will name it.
- Verified the fix against the original repro: the endpoint that returned `500 | text/html |
  <!doctype html>` now returns `500 | application/json | {"error":"ModuleNotFoundError: No module
  named 'twilio'"}`. In production that string will name the real exception, which is the point.
- Exercised all four `app_timezone` paths with logging on: valid override (silent), bad override
  (one WARNING), unset (silent), no tz database (one ERROR, returns UTC).

## Review triage 2026-08-08
Inline review (minerva spec/knowledge audit + code review of `git diff main...HEAD`).

- **F1 (low) → FIX.** The fallback re-attempted the *identical* lookup when `APP_TIMEZONE` was
  unset or already `America/New_York`, logging `unknown APP_TIMEZONE 'America/New_York' — falling
  back to America/New_York`. Nonsense on its face, and this unit is specifically about making
  diagnostics trustworthy. Replaced the two stacked try blocks with a deduped candidate loop
  (`dict.fromkeys`) that warns only for a genuinely unknown override.
- **F2 (low) → accepted.** `new URL(res.url)` would throw on an opaque response with an empty
  `url`; the outer catch renders "Send failed — try again". Same-origin fetches always populate
  `url`, so this is unreachable in practice and the degradation is already correct.
- **F3 (low) → accepted, documented.** The JSON error echoes the exception message, which for a
  Twilio failure could include the account SID. Single-user, password-protected app, and an
  unnamed error is exactly the state this unit exists to escape. Recorded in the proposal.
- **Spec fidelity: clean.** All six success criteria met with evidence.
- **Knowledge compliance: refines, does not violate.** [[012-pattern-fetch-content-type-session-detection]]
  is still correct that Content-Type must be checked before parsing; this unit adds that it is not
  *sufficient* as an expiry signal. Promoted as a bug entry rather than silently editing 012.
  The non-fatal contract of the scheduled path ([[016-decision-daily-digest-notifier]]) is
  untouched — only the manual endpoint changed.
