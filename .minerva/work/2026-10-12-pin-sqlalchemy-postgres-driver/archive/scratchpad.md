# Scratchpad: pin-sqlalchemy-postgres-driver

> **Ephemeral working memory.** Most of what lands here is noise — small
> decisions that don't matter, dead ends, momentary confusion. At feature
> completion, run `minerva:promote`: significant items get promoted to
> `.minerva/knowledge/`, `proposal.md` gets updated to match reality, and
> the raw scratchpad is archived.

## Decisions 2026-10-12
- [hardcoded check — clear] pre-flight: no collision — in_flight hits 014/020/022 are shipped units; no open PRs; no open-issue match; seed = this session's debug diagnosis + the user's go-ahead to fix and ship
- [solo] scope check: one unit, one PR, no phases (tier: solo predicate — additive pin + 1 helper, bounded surface (requirements.txt, app/__init__.py, one new test file), mechanically verifiable by named tests and the deploy phase, single concern (container boot), no new public interface, no knowledge conflict; parallel wave)
- [reviewed — clean] approach: A — pin SQLAlchemy<2.1 + explicit psycopg2 driver; rejected B (stay on 2.1: untested Postgres semantics, knowledge 033), C (pin only: next bump re-breaks), D (psycopg 3: driver migration in a hotfix) (tier: reviewer — production DB connection path, not provably small; parallel wave). Noted-but-dismissed: floating transitive deps (lockfile out of scope), sslmode/query-string and test-guard verification notes folded via whole-proposal
- [reviewed — folded] whole-proposal: criterion 3 unsatisfiable in-repo under the pin (driver assertion passes without the fix) → version-independent URI assertion + one-off 2.1.4 scratch-venv run; criterion 5 passed on the rollback build → deployment cause must name the merge commit, ACTIVE, no rollback, logged-in GET / (tier: reviewer; parallel wave)
- [rechecked — residual folded] whole-proposal: item 4 partially addressed — sslmode row added to criterion 2, uppercase schemes explicitly declined; low new concerns folded (psycopg2-binary in the scratch venv, credentials source)
- [reviewed — clean] completion verification: Verifier reproduced C1–C4 (328 passed in repo + pinned venvs; 7 passed under 2.1.4; main's create_app reproduces `No module named 'psycopg'`); C5 deferred to post-merge by construction (tier: reviewer floor — no interface beyond what the proposal approved; code review alongside)
- [solo] review triage: 3 FIX / 0 SUGGEST / 0 IGNORE — minerva audit: no findings; code review (local-diff, fresh-context subagent): docstring misattributed `postgres://` to DigitalOcean; test docstring should name the URI assertion as the guard; move `db` import to module level (tier: default-solo row — each had one dominant disposition)
- [solo] promote partition: PROMOTE 1 (bug entry: SQLAlchemy 2.1 default driver crashed boot — absorbs the boot-time import note and deploy-diagnosis recipe) / MERGE 1 (verification results into ## Approach) / DISCARD rest / TODO 1 (tier: default-solo row — no entry had two defensible buckets)
- [solo] TODO disposition: floating dependencies → issue #52, priority high (tier: default-solo row — clears all three bar conditions: writable failure scenario, it just blocked a deploy, a lockfile changes the build contract so it is not absorbable; one issue, within the soft cap)

## Work notes
- Criterion 1: fresh venv + `pip install -r requirements.txt` → sqlalchemy 2.0.54, alembic 1.20.0; full suite 328 passed on that fresh resolve.
- Criterion 3 one-off (scratch venv: sqlalchemy 2.1.4, psycopg2 2.9.13): branch `tests/test_app_config.py` → 7 passed; `main`'s `create_app()` with `DATABASE_URL=postgresql://u:p@h/d?sslmode=require` → `ModuleNotFoundError No module named 'psycopg'` (the production crash, reproduced through the real factory).
- `create_app` builds the engine at `init_app` and imports the DBAPI there without connecting — which is why the crash happens at boot (in `flask db upgrade`, before gunicorn) rather than on the first request.

## Review triage 2026-10-12
- [FIXED] #1 low app/__init__.py — `postgres://` is the Heroku-style form; `.env.example` documents `postgresql://`
- [FIXED] #2 low tests/test_app_config.py — docstring names the URI assertion as the in-repo guard
- [FIXED] #3 low tests/test_app_config.py — `db` imported at module level
