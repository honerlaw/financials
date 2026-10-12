# Proposal: uv-locked-dependencies

**Date**: 2026-10-12
**Status**: Shipped (2026-10-12)
**Closes**: #52

## Goal

Manage Python dependencies with `uv` instead of `requirements.txt`: declare them in
`pyproject.toml`, commit a `uv.lock`, and have the production image install exactly the
locked set — so a build installs what was tested, not whatever PyPI resolves at push time.

## Why

The user asked to move to `uv`. It also closes issue #52 (adopted at intake, priority high):
`requirements.txt` is almost entirely `>=` ranges and the Dockerfile re-resolves them on
every App Platform build. Earlier today that pulled SQLAlchemy 2.1.4, whose default Postgres
driver the image did not install, and the deploy of #51 crashed and rolled back (knowledge
`2026-10-12-bug-sqlalchemy-2-1-default-postgres-driver-crashed-boot`). PR #53 pinned that one
package; every other dependency still floats.

## Approach

*(Rewritten at promote: implemented as planned. The conditional reseeding in step 2 was not needed — the first lock already matched production. Review added `**/.venv/` and `.minerva/worktrees/` to `.dockerignore` and a console note in the Dockerfile.)*

1. **`pyproject.toml`** — a non-packaged uv project (`[tool.uv] package = false`; the app is
   run from the source tree, not installed). `[project] dependencies` carries every runtime
   requirement with the **same bounds** `requirements.txt` has today, including
   `SQLAlchemy>=2.0,<2.1` and its comment. Test-only tools (`pytest`, `pytest-flask`,
   `freezegun`) move to `[dependency-groups] dev`, so the production image no longer ships
   them. `requires-python = ">=3.12,<3.13"`, with `.python-version` = `3.12`, so the lock
   resolves only for the interpreter the image runs (`python:3.12-slim`) and local
   development uses it too (uv fetches 3.12 locally; the old 3.13 `venv/` becomes unused).
2. **`uv.lock`, reconciled to what production runs.** A plain `uv lock` would resolve every
   `>=` bound to today's newest release at once — the SQLAlchemy failure moved to lock time.
   So the lock is seeded from the last successful production build (deployment `d249aa0d`,
   commit `b6ead9d`, whose build log listed every package pip installed — captured to the
   work unit's scratchpad, so the check can be re-run): after `uv lock`, every runtime package
   whose locked version differs from that list is set back with
   `uv lock --upgrade-package <name>==<prod version>`. A trial lock already resolves to
   exactly production's versions, so this step is conditional — it only acts if PyPI moves
   before the lock is committed. The result is the
   set production already runs, now frozen with hashes (`uv sync` verifies them — the
   "with hashes" part of #52). From then on, bumping is an explicit, reviewable change
   (`uv lock --upgrade-package <name>`), never a side effect of a push.
3. **Dockerfile** — install a version-pinned `uv` from PyPI (`pip install --no-cache-dir
   uv==0.10.7`; PyPI is already a build dependency, so no new registry such as ghcr.io enters
   the production build path), copy `pyproject.toml`, `uv.lock` and `.python-version` first
   (layer cache), and run `uv sync --locked --no-dev`. `--locked` fails the
   build if the lock is out of date with `pyproject.toml`, rather than silently re-resolving.
   The environment lives at `/app/.venv`; `ENV PATH="/app/.venv/bin:$PATH"` keeps
   `entrypoint.sh`'s bare `flask` and `gunicorn` calls (including through `doppler run`)
   unchanged. `UV_PYTHON_DOWNLOADS=never` and `UV_PYTHON_PREFERENCE=only-system` so uv uses
   the image's Python and fails loudly if the base image ever stops matching
   `requires-python`; `UV_LINK_MODE=copy` and `UV_COMPILE_BYTECODE=1` for a no-cache image
   build. The pip-installed `uv` stays in the image's system site-packages (harmless; it is
   the tool `uv sync` ran with, and bumping it is a deliberate change). `.venv/` is added to `.dockerignore` so a local environment is never copied over the
   image's — along with `**/.venv/` and `.minerva/worktrees/`, so a local build from a
   checkout with active worktrees does not ship their environments. Rollback is a plain revert of the PR: the Dockerfile and `requirements.txt`
   change together.
4. **Delete `requirements.txt`.** Historical plan documents under `docs/superpowers/` that
   mention it are records of past work and are left alone.
5. **Developer instructions** — a short `## Development` section in `CLAUDE.md`
   (`uv sync`, `uv run pytest`, `uv add`, `uv lock --upgrade-package`), the one place
   project instructions live. It says that a bare `uv lock --upgrade` moves every package at
   once and that a change to `uv.lock` should be built (`docker build`) before it merges.

### Candidate approaches considered

- **A (recommended) — `pyproject.toml` + `uv.lock`, image installs with `uv sync --locked`.**
- **B — `uv pip compile` to a hashed `requirements.lock`, image keeps `pip install`.** Locks
  versions too, but keeps a requirements file as the contract — not what was asked.
- **C — `uv export` to `requirements.txt` at build time.** Same objection, plus a generated
  artifact that can drift from the lock.
- **D — lock with pip-tools.** Solves #52 but ignores the request to use uv.

## Success criteria

1. `requirements.txt` is gone; `pyproject.toml` declares the same runtime dependencies with
   the same bounds (SQLAlchemy `>=2.0,<2.1` with its comment) and a `dev` group holding
   `pytest`, `pytest-flask`, `freezegun`; `uv.lock` is committed and `uv lock --check`
   passes.
2. The runtime closure of the lock (`uv export --no-dev --no-hashes`, markers stripped,
   names normalized to lowercase-hyphen, Linux/3.12-applicable lines only) diffed against
   the package set the last successful production build installed (deployment `d249aa0d`,
   commit `b6ead9d`; the list is recorded in the scratchpad) differs in **exactly** these
   seven packages, all present only in production because only the `dev` group pulls them
   in: `freezegun`, `iniconfig`, `packaging`, `pluggy`, `pygments`, `pytest`,
   `pytest-flask`. Every other name and version is identical.
3. `uv sync` then `uv run pytest` passes the full suite on Python 3.12.
4. `docker build` succeeds locally (arm64 — a proxy; criterion 6 is the amd64 check), and in
   the built image: `pytest` is not importable, `sqlalchemy`
   is 2.0.x, `psycopg2` imports, `gunicorn --version` runs, and `flask --app wsgi --help`
   (with dummy `SECRET_KEY` / `APP_PASSWORD` and a SQLite `DATABASE_URL`) lists the `db`
   command `entrypoint.sh` calls.
5. Editing a bound in `pyproject.toml` without re-locking makes `docker build` fail at the
   `uv sync --locked` step (demonstrated once, not committed).
6. After merge, the App Platform deployment for the merge commit is `ACTIVE` and is still
   the active deployment 5 minutes later (no automated-rollback row above it), and a
   logged-in `GET https://financials.honerlaw.io/` returns 200.

## Open Questions

- Automated lock bumps (Dependabot / Renovate on `uv.lock`) are out of scope; bumps are
  manual `uv lock --upgrade-package` changes.
