# Followups: transactions-totals-and-nav-link

## 2026-05-20

- **Fix pre-existing failing test `tests/chat/test_routes.py::test_stream_returns_sse`.** Fails on `main` at commit `6d04e01` (predates this work unit) with `TypeError: fake_llm_client.<locals>.<lambda>() takes 1 positional argument but 2 were given` at `app/chat/routes.py:103`. The `_make_client(app, requested_model)` call now passes two args but the fake-LLM-client lambda in the test fixture only accepts one. Update the test fixture to accept both arguments. Out of scope for unit 001 — flagged here so it doesn't get forgotten.
