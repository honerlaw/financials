# Dependencies are managed with uv and the production image installs the committed lock

**Date**: 2026-10-12
**Type**: decision
**Theme**: deployment
**Summary**: `pyproject.toml` + committed `uv.lock`; the image runs `uv sync --locked --no-dev`, so builds install the tested set.
**Context**: .minerva/work/2026-10-12-uv-locked-dependencies (see git history if the worktree has been cleaned up)

## Context

`requirements.txt` was almost entirely `>=` ranges, and the Dockerfile re-resolved them on
every App Platform build, so production ran whatever PyPI offered at push time. That is how
an unpinned SQLAlchemy 2.1 crashed a deploy
([[2026-10-12-bug-sqlalchemy-2-1-default-postgres-driver-crashed-boot]]); the hotfix pinned
one package and left the rest floating (issue #52). The user asked to use uv instead of
`requirements.txt`, and #52 was adopted into the same change.

## Finding

1. **`pyproject.toml` declares, `uv.lock` decides.** The project is non-packaged
   (`[tool.uv] package = false`). Runtime dependencies keep the bounds `requirements.txt`
   had, including `SQLAlchemy>=2.0,<2.1` and its reason; `pytest`, `pytest-flask` and
   `freezegun` are a `dev` dependency group the production image no longer ships.
   `requires-python = ">=3.12,<3.13"` plus `.python-version` = `3.12` lock and develop
   against the image's interpreter only.
2. **The first lock was reconciled against production, not freshly resolved.** A fresh
   resolve could have moved every `>=` package at once — the SQLAlchemy failure moved to
   lock time. The last good build's installed set (from its `doctl ... --type build` log)
   was the baseline: the lock's runtime closure matched it name-for-name and
   version-for-version, differing only by the seven packages the `dev` group alone pulls
   in. The planned `--upgrade-package <name>==<version>` reseeding was not needed.
3. **The Dockerfile installs the lock, refusing a stale one.** `pip install uv==0.10.7`
   (PyPI was already a build dependency, so no new registry such as ghcr.io entered the
   build path), copy `pyproject.toml` / `uv.lock` / `.python-version`, then
   `uv sync --locked --no-dev --no-cache`. `--locked` fails the build when the two files
   disagree — demonstrated by editing a bound without re-locking.
   `UV_PYTHON_PREFERENCE=only-system` + `UV_PYTHON_DOWNLOADS=never` make uv use the image's
   Python and fail loudly if the base image stops matching `requires-python`.
4. **Boot is unchanged.** `/app/.venv/bin` goes first on `PATH`, so `entrypoint.sh`'s bare
   `flask` / `gunicorn` — also under `doppler run`, which inherits `PATH` — resolve to the
   locked environment. Verified with an amd64 build booted against a throwaway Postgres:
   the full migration chain applied and gunicorn served requests.

## Implications

- **Bump on purpose.** `uv lock --upgrade-package <name>` moves one package; a bare
  `uv lock --upgrade` moves everything at once and should be avoided. Build the image
  before merging any `uv.lock` change, because production deploys on every push to `main`
  (CLAUDE.md § Development says the same).
- **The lock carries hashes and `uv sync` verifies them.** Nothing bumps the lock
  automatically; a stale lock is now a slow-security-update risk rather than a broken-deploy
  risk.
- **In a production console, the system `pip` is not the app's environment** — `/app/.venv`
  has no pip, and `uv run` would sync the dev group into it. Use
  `uv pip list --python /app/.venv`.
- **Local development uses `.venv` (Python 3.12) via `uv sync` / `uv run pytest`.** The
  older `venv/` directory is no longer used.
- **`.dockerignore` excludes `**/.venv/` and `.minerva/worktrees/`**, so a local
  `docker build .` from a checkout with active worktrees does not ship their environments.

## Related

- [[2026-10-12-bug-sqlalchemy-2-1-default-postgres-driver-crashed-boot]] — builds on: that fix pinned one package; this locks all of them, closing the issue it deferred (#52).
- [[017-pattern-migration-chain-is-postgres-only]] — see also: why verifying the image's boot needed a real Postgres rather than SQLite.
- [[011-decision-doppler-hybrid-config]] — see also: `entrypoint.sh`'s `doppler run` wrapper, whose `PATH` inheritance the venv-first `PATH` relies on.
