# Scratchpad: transactions-totals-and-nav-link

> **Ephemeral working memory.** Most of what lands here is noise — small
> decisions that don't matter, dead ends, momentary confusion. At feature
> completion, run `minerva:promote`: significant items get promoted to
> `.minerva/knowledge/`, `proposal.md` gets updated to match reality, and
> the raw scratchpad is archived.

## Pre-existing test failure (not caused by this work)

`tests/chat/test_routes.py::test_stream_returns_sse` fails on `main` (commit
`6d04e01`) with `TypeError: fake_llm_client.<locals>.<lambda>() takes 1
positional argument but 2 were given` at `app/chat/routes.py:103`. The
`_make_client(app, requested_model)` call now passes two args but the fake in
the test still uses a one-arg lambda. Out of scope for `001-...`; verified by
checking out `main` and running the failing test directly.

