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
