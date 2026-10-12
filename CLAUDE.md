## minerva

This project uses [minerva](https://github.com/honerlaw/agent-marketplace/tree/main/plugins/minerva) for durable record discipline.

- `.minerva/knowledge/` — concrete, past-tense knowledge artifacts: decisions made, bugs fixed, patterns discovered. Read when starting work in this repo.
- `.minerva/work/` — historical proposals and replans. Grep when you need the reasoning behind a past feature.

Active work units live at `.minerva/work/NNN-<slug>/`. Invoke the `minerva:using-minerva` skill (via the `Skill` tool) for the full methodology.

## Development

Dependencies are managed with [uv](https://docs.astral.sh/uv/): `pyproject.toml` declares them, `uv.lock` pins the exact versions, and the production image installs the lock with `uv sync --locked --no-dev` (so a stale lock fails the build).

- `uv sync` — create/update `.venv` (Python 3.12, per `.python-version`) with runtime + `dev` dependencies.
- `uv run pytest` — run the test suite.
- `uv add <pkg>` / `uv add --dev <pkg>` — add a dependency; commit `pyproject.toml` and `uv.lock` together.
- `uv lock --upgrade-package <pkg>` — bump one package deliberately. A bare `uv lock --upgrade` moves **every** package at once — the way an unpinned SQLAlchemy 2.1 once crashed a deploy — so avoid it.
- Build the image (`docker build .`) before merging any change to `uv.lock`: production deploys on every push to `main`.

