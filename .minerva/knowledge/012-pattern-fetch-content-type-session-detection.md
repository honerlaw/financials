# `fetch()` session-expiry detection needs a Content-Type check, not `r.ok`

**Date**: 2026-06-13
**Type**: pattern
**Summary**: A `fetch()` against a Flask `@login_required` route cannot detect session expiry with `!r.ok` — the browser follows the 302 to `/login` transparently, so check the response Content-Type before parsing.
**Context**: .minerva/work/007-infinite-scroll-transactions (see git history if the worktree has been cleaned up)

## Context

Work unit 007-infinite-scroll-transactions added a client-side `fetch()` call to `/api/transactions`, a route protected by `@login_required`. When the user's session expires mid-session, the route returns a 302 redirect to `/login`. The initial fix attempt used `if (!r.ok)` to detect non-success responses.

## Finding

`if (!r.ok)` does **not** detect Flask session expiry. `fetch()` uses `redirect: 'follow'` by default, so the browser follows the 302 transparently. The JS sees the `/login` HTML page as a **200 OK** response with `r.ok === true`. Calling `r.json()` on HTML throws a `SyntaxError` which lands in `.catch()` — but with `loading = false` and the observer still active, the next scroll event retriggers the same broken fetch, creating an infinite retry loop with a "Failed to load more" message and no path to re-authentication.

The correct detection is a **Content-Type check before `.json()`**:

```javascript
fetch(url)
  .then(function (r) {
    if (!(r.headers.get('content-type') || '').includes('application/json')) {
      observer.disconnect();
      window.location.href = '/login';
      return null;
    }
    return r.json();
  })
  .then(function (data) {
    if (!data) return;
    // … process data
  })
  .catch(function () {
    // genuine network errors — observer still active for retry
    loading = false;
    status.textContent = 'Failed to load more — scroll up and try again.';
  });
```

The Content-Type check catches the redirect-to-login case (HTML body) regardless of status code, and redirects to `/login`. Genuine network failures still fall through to `.catch()`.

## Implications

- **Any client-side `fetch()` call against a `@login_required` Flask route** must use a Content-Type check (or `{redirect: 'manual'}` with an `r.type === 'opaqueredirect'` check) rather than `r.ok` to detect session expiry.
- `r.ok` is only reliable when the server returns a non-2xx status directly — not when the auth layer issues a redirect that the browser follows.
- The `{redirect: 'manual'}` approach is an alternative: it surfaces the 302 as `r.type === 'opaqueredirect'` before the browser follows it, enabling a redirect to `/login` without parsing the response body.
- This applies to future fetch() calls in `chat.js` and any other client-side JS in this app.

## Related

- [[004-pattern-seed-relative-dates-in-time-sensitive-tests]] — see also
