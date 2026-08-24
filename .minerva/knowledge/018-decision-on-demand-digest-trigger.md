# On-demand digest: a second trigger that is deliberately dedup-independent

**Date**: 2026-08-08
**Type**: decision
**Summary**: A dashboard button texts the daily digest on demand via `send_digest_now`, which neither reads nor writes `DailyDigest` so it never interacts with the 7am job in either direction; `is_configured` is the one soft-disable predicate both the button and the endpoint must use.
**Context**: .minerva/work/017-send-digest-on-demand

## Context

[[016-decision-daily-digest-notifier]] made the digest a scheduled artifact —
one text per recipient per day, at 7am, deduped on `(sent_date, recipient)`.
That left no way to ask "where do we stand?" mid-afternoon, and no way to verify
the feature without waiting for the next morning. Unit 017 adds a second
*trigger* for the same artifact, not a second artifact: `send_digest_now`
alongside `send_daily_digest`, behind a "Text me this" button in the dashboard's
Spending card header.

## Decisions

1. **The manual path neither reads nor writes `DailyDigest`.** It is
   dedup-independent in *both* directions: a press works after today's
   scheduled digest already went out, and never suppresses tomorrow's. Writing
   a row was the tempting alternative — it would make the button "claim" the
   day — but that gives a control labelled "send now" an invisible second
   effect, where pressing at 6am silently cancels the morning text. The
   accepted cost is that pressing at 06:55 yields two texts. Rare and harmless,
   and strictly better than a button that appears to do nothing.

2. **Two small functions, not a `force=True` flag.** The scheduled path's
   contract — the one that runs unattended every morning — is left completely
   untouched; the two share only the pure builders (`digest_body`,
   `_week_spent`, `_account_balances`), so the manual text and the 7am text are
   byte-identical for the same data. A flag would have put a dedup branch
   inside every step of the scheduled path.

3. **`is_configured(config)` is the single soft-disable predicate.** The
   dashboard needs the gate *before* a press, to render the button disabled
   rather than only failing on click — and the first implementation re-derived
   it in `routes.py` with a bare `.strip()` on the raw recipients string. That
   silently disagrees with `_recipients()`: a value like `","` is truthy after
   stripping (button enabled) but parses to zero recipients (press → 400).
   Any future caller needing "can we text right now?" must call
   `is_configured`, never re-derive it. It deliberately constructs no
   `TwilioSender`, so the lazy `twilio` import from
   [[010-decision-budget-alert-notifier]] stays lazy on every page load.

4. **Synchronous endpoint, reporting the outcome.** `POST /api/digest/send`
   sends inline and returns `{'configured', 'sent', 'failed'}` — 400 when
   soft-disabled, 502 when every send failed, 200 otherwise (including partial
   failure, which is a success with a caveat). This is the opposite choice from
   `/api/sync`, which fires a background thread and returns immediately,
   because the whole point of a button is to say what happened. Soft-disable
   surfacing as a real 400 message rather than a silent success is part of the
   same reasoning.

## Known limitations / operational

- **A press occupies the single worker.** The app runs `gunicorn --workers 1`,
  so a hung Twilio call blocks all requests for up to the `TwilioSender` 10s
  timeout per recipient (bounded overall by gunicorn's 120s). Accepted: the
  person waiting is the one who pressed the button. Revisit if recipients ever
  grow beyond a handful.
- **No rate limit.** Repeated presses send repeated texts, by design. The
  button disables itself while a request is in flight, which handles the
  double-click case but nothing deliberate.

## Related

- [[016-decision-daily-digest-notifier]] — builds on
  the scheduled digest whose message and builders this reuses unchanged.
- [[010-decision-budget-alert-notifier]] — see also
  the soft-disable gate and lazy `twilio` import that `is_configured` preserves.
- [[012-pattern-fetch-content-type-session-detection]] — see also
  the Content-Type check the button's `fetch` needs against a `@login_required` route.
- [[019-bug-non-json-response-conflated-with-session-expiry]] — see also
- [[022-decision-digest-four-week-spend-history]] — see also
