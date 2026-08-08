# A crashed endpoint and an expired session both return non-JSON — Content-Type can't tell them apart

**Date**: 2026-08-08
**Type**: bug
**Summary**: The digest button redirected to `/login` on every press because its `fetch` treated any non-JSON response as session expiry, so an unhandled 500 rendered as a phantom logout; the precise expiry signal is `res.redirected` plus the final URL, and API endpoints must fail as JSON.
**Context**: .minerva/work/018-fix-digest-button-error-masking

## Symptom

Pressing the dashboard's "Text me this" button navigated to `/login` and sent no
SMS. It looked exactly like a session expiry. It was not — the session was fine.

## Root cause

Two defects on the same path, both shipped in unit 017:

1. `POST /api/digest/send` had **no exception handling**, so anything raised
   inside it escaped as Flask's default HTML 500 page.
2. The button's `fetch` treated **any** non-JSON response as an expired session
   and hard-redirected to `/login`, discarding the response.

Reproduced locally: `status: 500`, `content-type: text/html`, for both a
placeholder and a well-formed Twilio SID — so the error was thrown before any
network call, at `_sender_from_config`.

The deeper mistake was applying
[[012-pattern-fetch-content-type-session-detection]] as though it were an
*identification* rule. It is a **parsing-safety** rule: check Content-Type
before `r.json()` so an HTML body doesn't throw. It says nothing about *why*
the body is HTML — and a crashed endpoint is non-JSON just like a login
redirect. Conflating them turns every server error into a fake logout, which is
the worst possible disguise: it blames the user's session, invites a pointless
re-login, and destroys the error text that would have explained it.

## Fix

- **Endpoints fail as JSON.** The route catches, logs the traceback via
  `current_app.logger.exception`, and returns
  `500 {'error': '<ExceptionType>: <message>'}` truncated to 300 chars. The
  message is deliberately echoed to the client: this is a single-user,
  password-protected app, and a generic "something went wrong" leaves the user
  as stuck as the fake logout did. It could include a Twilio account SID in the
  exception text; accepted for that reason.
- **The client keys on the real signal.** `fetch` follows the `@login_required`
  302 transparently but records it: `res.redirected === true` and
  `new URL(res.url).pathname === '/login'`. Redirect only on that. Any *other*
  non-JSON response renders as `Server error (<status>) — check the logs`. The
  Content-Type check stays, in its proper role as a parse guard.

## Generalizable rule

For any `fetch` against a `@login_required` JSON route: **redirect on
`redirected`-to-`/login`, not on "not JSON."** Non-JSON is the union of
"session expired" and "server crashed", and only one of those is fixed by
logging in again.

## Related

- [[012-pattern-fetch-content-type-session-detection]] — refines
  the Content-Type check, which remains necessary as a parse guard but is not sufficient to identify expiry.
- [[018-decision-on-demand-digest-trigger]] — builds on
  the button and endpoint this bug was found in.
- [[020-pattern-injected-fakes-hide-construction-failures]] — see also
  why the test suite could not catch this.
