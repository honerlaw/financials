# Proposal: infinite-scroll-transactions

**Date**: 2026-06-13
**Status**: Shipped (2026-06-13)

## Goal

Replace the manual «prev / next» pagination UI on the transactions index page with
infinite scroll — the next 50 transactions load automatically when the user scrolls near
the bottom of the table.

## Why

The current «page X of Y» control requires a deliberate button click to see older
transactions, which interrupts the natural flow of browsing a transaction history. Infinite
scroll removes that friction: the user simply scrolls and the table extends.

## Approach

- **New `/api/transactions` JSON endpoint** in `app/routes.py` — accepts `page`,
  `institution`, and `month` query params; applies the same filter logic as the existing
  `index()` view; returns `{items: [...], has_next: bool, next_page: int}` where each item
  carries `date`, `description`, `merchant_name`, `institution_name`, `amount`, and
  `amount_class` (text-danger / text-success / text-muted) pre-computed on the server.
- **Sentinel element** — a `<div id="scroll-sentinel">` placed immediately after the
  `<tbody>` tag in `index.html`, outside the table (to avoid invalid HTML).
- **IntersectionObserver** JS in `index.html`'s `{% block scripts %}` — watches the
  sentinel; when it enters the viewport, fires a fetch to `/api/transactions?page=N&…`,
  appends new `<tr>` rows, and advances the page counter. Stops observing when
  `has_next=false`. A simple loading indicator (aria-live span) shows while fetching. Session
  expiry is detected via a Content-Type check before calling `.json()` — `@login_required`
  returns a 302 that the browser follows transparently, making the login page appear as a
  200 response; `r.ok` cannot detect this (see knowledge `005-pattern-fetch-content-type-session-detection`).
- **Filters preserved** — `institution` and `month` query params are read from the
  current URL's `URLSearchParams` and forwarded on every fetch, so filtering still works
  correctly. The existing `applyFilter()` already does a full page reload, so filter
  changes naturally reset scroll state.
- **Remove manual pagination** — the `{% if transactions.pages > 1 %}` `<nav>` block is
  removed from `index.html`.
- **Page 1 stays server-rendered** — `index()` continues to render the first page of
  transactions in the initial HTML response; JS loads pages 2+ on demand.
- **Tests** — new tests for `/api/transactions` in `tests/test_routes.py` covering:
  pagination (page 1, page 2), institution filter, month filter, `has_next` flag.

## Success criteria

1. Scrolling to the bottom of the transactions table automatically loads the next page of
   50 transactions without any button click.
2. All active filter parameters (institution, month) are carried through to infinite-scroll
   fetches and return correctly filtered results.
3. When there are no more pages, loading stops and no further requests are fired.
4. The «prev / next» manual pagination UI is gone from the page.
5. All existing tests pass; new `/api/transactions` endpoint tests pass.

## Open Questions

- None — scope is clear and approach is unambiguous.
