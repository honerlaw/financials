# A route test that freezes the clock must log in under the frozen clock

**Date**: 2026-11-07
**Type**: pattern
**Theme**: testing
**Summary**: Flask's signed session cookie is timestamped, so a login made before `freeze_time` reads as coming from the future and is refused. Log in inside the frozen block.
**Context**: .minerva/work/2026-11-07-calendar-month-cadence (see git history if the worktree has been cleaned up)

## Context

The /recurring route reads `date.today()`. To make a calendar-month fixture deterministic, the
route test was decorated with `@freeze_time('2026-06-01')` and used the `auth_client` fixture.
Every request was redirected to `/login`.

## Finding

Fixtures are set up before the decorated test body runs, so `auth_client` logged in at the real
time. Flask's default session (`SecureCookieSessionInterface`, built on itsdangerous) signs the
cookie with a timestamp and checks its age on every request. Under a clock frozen *before* the
login, the cookie's age is negative, so the session is rejected and the client is logged out.
Nothing raises an error; the page just redirects.

The fix is to take the plain `client` fixture and log in inside the frozen test body:
`client.post('/login', data={'password': 'testpass'})`. The test
`test_recurring_counts_a_monthly_bill_paid_on_a_drifting_day` in `tests/test_bills.py` does this.

## Implications

- Freezing the clock in a route test whose freeze time is earlier than the real time means
  `auth_client` cannot be used. A freeze time later than the real time works only until the
  cookie's maximum age is exceeded.
- The symptom is a 302 to `/login`, or a `_section` helper failing to find a heading, not an
  authentication error. Check the clock before checking the route.

## Related
- [[004-pattern-seed-relative-dates-in-time-sensitive-tests]] — when a test should inject or freeze the clock
- [[2026-11-07-decision-monthly-gaps-are-regular-across-one-calendar-month]] — the first route test that needed it
