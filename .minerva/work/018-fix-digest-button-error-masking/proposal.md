# Proposal: fix-digest-button-error-masking

**Date**: 2026-08-08
**Status**: Shipped (2026-08-08)

## Goal

Stop the "Text me this" button from reporting a phantom logout when the send
fails, and show the actual error instead — so the underlying production failure
becomes diagnosable rather than invisible.

## Why

Reported symptom: pressing the button redirects to `/login` and no SMS arrives.
The user is not being logged out. Investigation (this session's `minerva:debug`
run) reproduced the mechanism:

- `POST /api/digest/send` has **no exception handling**, so anything raised
  inside it escapes as Flask's HTML 500 page.
- The button's `fetch` treats **any** non-JSON response as an expired session
  and hard-redirects to `/login`, discarding the error.

Reproduced locally: status 500, `content-type: text/html`, for both a
placeholder and a well-formed Twilio SID.

This is an asymmetry introduced in unit 017. The 7am path is wrapped in
`_send_daily_digest_safe`, which catches and logs exactly this class of failure
([[016-decision-daily-digest-notifier]]); the manual path shipped with no
equivalent. Two contributing defects surfaced with it:

- **The test suite structurally cannot catch it.** Every notifier test injects a
  fake sender, so `_sender_from_config` — the line that throws — never executes.
  The full 226-test suite passes with `twilio` uninstalled.
- **`app_timezone`'s fallback can raise the error it is catching.** If the tz
  database is absent, `ZoneInfo(name)` raises and the recovery
  `ZoneInfo(DEFAULT_TIMEZONE)` raises identically, uncaught. `send_digest` calls
  `local_today` on its first line, so this is on the same failure path.

The real production exception is still unknown — there are no logs to hand. Fix
1 is what makes the next press name it.

## Approach (as shipped)

### 1. The endpoint reports failures as JSON — `app/routes.py`

Wrap `send_digest`'s body. On an unexpected exception: log the full traceback
via `current_app.logger.exception`, and return
`500 {'error': '<ExceptionType>: <message>'}` — JSON, so the client can render
it.

The message is deliberately included rather than a generic "something went
wrong". This is a single-user, password-protected app, and naming the exception
is the entire point of the change; a generic string would leave the user exactly
where they are now. The message is truncated to 300 chars, and the full
traceback stays server-side.

### 2. The button distinguishes expiry from failure — `app/templates/index.html`

`fetch` follows the `@login_required` 302 transparently and exposes the fact:
`res.redirected` is true and `res.url` ends at `/login`. That is a precise
session-expiry signal, so redirect only on it. Any other non-JSON response is a
server error and renders as one ("Server error — check the logs") instead of
masquerading as a logout.

This refines [[012-pattern-fetch-content-type-session-detection]] rather than
contradicting it: the Content-Type check remains necessary (a 302-to-HTML still
must not reach `r.json()`), but it is **not sufficient** as an expiry signal on
its own — every other non-JSON response is a crash, and conflating the two hides
outages behind a fake login screen.

### 3. `app_timezone` cannot raise from its own recovery — `app/localtime.py`

Guard the fallback. If `ZoneInfo(DEFAULT_TIMEZONE)` also fails, the tz database
is missing entirely; log an error and return `timezone.utc`. UTC is the wrong
*schedule* but a working *app* — and unit 016 chose the New York default
precisely to avoid silently landing on UTC, so this path logs loudly at ERROR.

Shipped as a deduped candidate loop rather than two stacked `try` blocks: the
first cut re-attempted the identical lookup when `APP_TIMEZONE` was unset, and
logged `unknown APP_TIMEZONE 'America/New_York' — falling back to
America/New_York`. Misleading diagnostics in a unit about trustworthy
diagnostics. (Found in review — finding F1.)

### 4. Close the test gap — `tests/test_notifications.py`

Add coverage that executes the real `_sender_from_config` construction with a
stubbed `twilio` module in `sys.modules`, asserting both that a working stub
produces a sender and that a raising stub surfaces as an endpoint 500 with JSON
rather than HTML. This runs identically whether or not `twilio` is installed
locally.

### Rejected alternatives

- **Return 401 JSON from `login_required` for `/api/*` paths.** A cleaner
  signal, but it changes a decorator every endpoint shares — a much wider blast
  radius than this bug warrants, and it would need every existing `fetch` audited.
- **Wrap the endpoint in the existing `_send_daily_digest_safe`.** That helper
  swallows failures to protect the *sync*; the button needs the opposite —
  failures surfaced to the caller.
- **Generic error message.** Leaves the production cause invisible, which is the
  actual complaint.

## Success criteria

1. A failure inside `POST /api/digest/send` returns JSON with a 500 status and
   an `error` naming the exception — never an HTML page.
2. The button renders that error inline; it redirects to `/login` only when the
   response actually redirected to the login page.
3. A genuine session expiry still redirects to `/login`.
4. `app_timezone` returns a usable tzinfo even when no tz database exists, and
   logs at ERROR when it degrades to UTC.
5. A test exercises the real `_sender_from_config` construction path, passing
   whether or not `twilio` is installed.
6. `pytest` passes.

## Open Questions

The production exception is still unidentified — this change is what surfaces
it. If it turns out to be invalid Twilio credentials, a follow-up may want
`is_configured` to distinguish "present" from "valid", which cannot be done
without a network call.

## Verification

`pytest`: 232 passed (+6).

The original repro, before and after:

```
BEFORE  500 | text/html; charset=utf-8      | <!doctype html> … 500 Internal Server Error
AFTER   500 | application/json              | {"error":"ModuleNotFoundError: No module named 'twilio'"}
```

(The local venv lacks `twilio`; in production that string will name whatever
actually throws there — which is the point of the change.)

All four `app_timezone` paths exercised with logging enabled: valid override
silent, bad override one WARNING, unset silent, no tz database one ERROR
returning UTC.

Accepted and recorded in [[019-bug-non-json-response-conflated-with-session-expiry]]:
the JSON error echoes the exception message, which for a Twilio failure could
include the account SID. Single-user password-protected app, and an unnamed
error is the state this unit exists to escape.
