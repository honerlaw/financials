# Scratchpad: uv-locked-dependencies

> **Ephemeral working memory.** Most of what lands here is noise — small
> decisions that don't matter, dead ends, momentary confusion. At feature
> completion, run `minerva:promote`: significant items get promoted to
> `.minerva/knowledge/`, `proposal.md` gets updated to match reality, and
> the raw scratchpad is archived.

## Decisions 2026-10-12
- [hardcoded check — clear] pre-flight: no collision — in_flight hits 014/020/022 are shipped units; no open PRs
- [escalated to user] open-issue match: #52 (floating dependencies, priority high) matches "use uv instead of requirements.txt" — user chose "Adopt #52 and extend"; **Closes**: #52 written at creation (global escalation counter: 1)
- [reviewed — clean] scope check: one unit, one PR (tier: reviewer — rewrites the production build path, not provably small; parallel wave). Skeptic noted: confirm no other requirements.txt consumer (none: no .github, Dockerfile only), httpx is runtime (app/chat/openrouter.py)
- [reviewed — folded] approach: A (pyproject + uv.lock, uv sync --locked --no-dev); rejected B (uv pip compile → requirements.lock), C (uv export at build), D (pip-tools) — none use uv as asked. Folded: lock seeded from production's installed set instead of a fresh resolve (lock-time float = the SQLAlchemy failure class); uv from PyPI (pip install uv==0.10.7) instead of ghcr.io (new registry in the build path); requires-python <3.13; UV_PYTHON_PREFERENCE=only-system, UV_LINK_MODE=copy, UV_COMPILE_BYTECODE=1; .python-version copied; CLAUDE.md warns on bare ; revert note (tier: reviewer — interface-clause doubt on deleting requirements.txt passed to the Skeptic; answered no: only consumer is the Dockerfile, rewritten here; parallel wave)
- [rechecked — clean] approach: fold-audit — all 8 items addressed; new concerns low (marker-conditional packages, mechanical dev-only set) — folded as criterion-2 wording
- [reviewed — clean] whole-proposal (restart): first-wave review stale because the approach fold rewrote ## Success criteria (criterion 2); re-reviewed at reviewer tier — accept. Write-up clarifications applied, decision unchanged: criterion 2 names the exact 7-package dev-only difference + normalization; baseline recorded here; seeding step marked conditional; local arm64 docker build labelled a proxy (tier: reviewer; parallel wave restart)

## Work notes
- Production baseline (deployment d249aa0d, commit b6ead9d, from `doctl apps logs <app> financials --deployment d249aa0d-896f-4d1c-98cc-50580fdcf853 --type build`, "Successfully installed" line):
  `aiohappyeyeballs-2.7.1 aiohttp-3.14.5 aiohttp-retry-2.9.1 aiosignal-1.4.0 alembic-1.20.0 annotated-types-0.8.0 anyio-4.15.1 APScheduler-3.11.3 attrs-26.1.0 blinker-1.9.0 certifi-2026.7.22 charset_normalizer-3.5.2 click-8.5.0 flask-3.1.3 flask-migrate-4.1.0 flask-sqlalchemy-3.1.1 freezegun-1.5.5 frozenlist-1.8.0 greenlet-3.5.6 gunicorn-26.2.0 h11-0.16.0 httpcore-1.0.9 httpx-0.28.1 idna-3.20 iniconfig-2.3.1 itsdangerous-2.2.0 jinja2-3.1.6 Mako-1.4.3 markupsafe-3.0.4 multidict-7.1.0 nulltype-2.3.1 packaging-26.3 plaid-python-45.0.0 pluggy-1.6.0 propcache-0.5.4 psycopg2-binary-2.9.13 pydantic-2.14.1 pydantic-core-2.50.1 pygments-2.21.0 PyJWT-2.15.1 pytest-9.1.1 pytest-flask-1.3.0 python-dateutil-2.9.0.post0 python-dotenv-1.2.4 requests-2.34.2 six-1.17.0 SQLAlchemy-2.0.54 twilio-9.11.2 typing-extensions-4.16.0 typing-inspection-0.4.4 tzdata-2026.5 tzlocal-5.4.4 urllib3-2.8.0 werkzeug-3.1.9 yarl-1.25.1 `
