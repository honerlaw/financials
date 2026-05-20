# Proposal: fix-fake-llm-client-arity

**Date**: 2026-05-20
**Status**: Shipped (2026-05-20)

## Goal

Make `tests/chat/test_routes.py::test_stream_returns_sse` pass again by updating the `fake_llm_client` fixture's monkeypatched lambda to match the `(app, model)` signature that `app.chat.routes._make_client` now uses.

## Why

The chat-model picker work (commit `b7468bd` "fix: use real OpenRouter slugs in chat-model picker") changed `_make_client` from a one-argument function to a two-argument function (`app, model`) so the route could honor the requested model. The test fixture at `tests/chat/test_routes.py:18` was not updated alongside, so the monkeypatched lambda still accepts a single positional argument:

```python
monkeypatch.setattr('app.chat.routes._make_client', lambda app: FakeClient())
```

As of 2026-05-20 the test fails with `TypeError: fake_llm_client.<locals>.<lambda>() takes 1 positional argument but 2 were given` at `app/chat/routes.py:103`. This is the only followup recorded in `.minerva/work/001-transactions-totals-and-nav-link/followups.md`.

## Approach

1. **Update the fixture.** Edit `tests/chat/test_routes.py:18`:
   - From: `monkeypatch.setattr('app.chat.routes._make_client', lambda app: FakeClient())`
   - To:   `monkeypatch.setattr('app.chat.routes._make_client', lambda app, model: FakeClient())`

   The lambda parameters are intentionally unused — the `FakeClient` doesn't need either — but the arity must match the production callsite so monkeypatching is transparent.

2. **Verify the failing test now passes.** Run `pytest tests/chat/test_routes.py::test_stream_returns_sse`.

3. **Verify the full suite still passes.** Run `pytest tests/` with no `--deselect` flag.

4. **Clear the followup.** Delete the entry from `.minerva/work/001-transactions-totals-and-nav-link/followups.md`. If the file becomes empty (no remaining bullets), remove the file entirely so future `minerva:propose` runs don't read a stale stub.

## Success criteria

- `pytest tests/chat/test_routes.py::test_stream_returns_sse` exits 0.
- `pytest tests/` exits 0 with no `--deselect` flag and the full collected-count of tests passes.
- The chat-test-arity bullet is gone from `.minerva/work/001-transactions-totals-and-nav-link/followups.md` (or the file is deleted if no bullets remain).

## Open Questions

_None._
