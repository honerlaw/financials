# Doppler migration runbook

This app uses [Doppler](https://doppler.com) as the single source of truth for
application configuration and secrets. Because the app reads everything through
`os.getenv` (`app/__init__.py`), Doppler only has to *populate the environment* —
there are no application code changes. This document covers first-time setup, the
staged production cutover, rollback, and day-2 operations.

## What lives where

| Value | Source |
|---|---|
| `SECRET_KEY`, `APP_PASSWORD`, `PLAID_*`, `OPENROUTER_*`, `CHAT_*`, `TWILIO_*`, `BUDGET_ALERT_RECIPIENTS` | **Doppler** |
| `DATABASE_URL`, `DATABASE_ADMIN_URL` | **DigitalOcean managed-DB binding** (NOT Doppler) |
| `DOPPLER_TOKEN` | **DO App Platform** dashboard (the one bootstrap secret) |

### ⚠️ Do NOT move the database URLs into Doppler

`DATABASE_URL`/`DATABASE_ADMIN_URL` are injected by DO's managed-database binding,
which also handles connection-string rotation. Keeping them there is a deliberate
exception to "single source of truth." `entrypoint.sh` runs `doppler run` with
`--preserve-env="DATABASE_URL,DATABASE_ADMIN_URL"` so that even if a `DATABASE_URL`
is accidentally added to Doppler, the DO-injected value still wins. Moving these
into Doppler would defeat that guard and risk pointing the app at the wrong
database.

## How the entrypoint decides

`entrypoint.sh` uses Doppler **only when `DOPPLER_TOKEN` is set and the `doppler`
CLI is present**; otherwise it runs on plain environment variables. The same
image works both ways, which is what makes the cutover staged and reversible. It
logs which mode it chose on boot:

- `[entrypoint] secrets via doppler run (v3.76.0)`
- `[entrypoint] DOPPLER_TOKEN unset or doppler CLI missing — using plain environment`

The Doppler CLI version is pinned in the `Dockerfile` (`ARG DOPPLER_CLI_VERSION`).
`doppler run` **fails closed** — a bad/expired token aborts boot (verified: exit 1,
the app never starts on empty config).

## One-time Doppler setup

1. Create a Doppler project named `financials` with configs `dev` and `prd`.
2. Populate each config with the values from `.env.example` (everything except the
   database URLs and `DOPPLER_TOKEN`).
3. Local dev:
   ```sh
   doppler login
   doppler setup           # reads doppler.yaml → project=financials, config=dev
   doppler run -- flask --app wsgi run
   ```
   (Plain `.env` still works too — see `.env.example`.)

## Staged production cutover (zero-downtime)

Doppler **overrides** existing OS env vars by default (`--preserve-env` defaults to
`"false"`), so once the token is live, Doppler's values take over for every var
except the `--preserve-env`'d database URLs. Order matters:

1. **Populate Doppler `prd`** with the exact current production values first.
   (If a value is wrong here, it will override the DO dashboard value once the
   token is set.)
2. **Mint a service token**: Doppler → project `financials` → config `prd` →
   Access → generate a **read-only** service token.
3. **Deploy the new image** (with the Doppler CLI baked in) *without* setting
   `DOPPLER_TOKEN`. It boots on the existing DO env vars — no behavior change.
   Confirm the boot log shows the *plain environment* line.
4. **Set `DOPPLER_TOKEN`** as a SECRET env var in the DO App Platform dashboard
   and redeploy/restart. Confirm the boot log now shows *secrets via doppler run*
   and the app is healthy (Plaid sync works, chat works, login works).
5. **Remove the now-redundant plain env vars** from the DO dashboard (keep
   `DATABASE_URL`/`DATABASE_ADMIN_URL` and `DOPPLER_TOKEN`). Redeploy; confirm
   still healthy — the app is now sourcing config from Doppler.

### Verify against the pinned CLI during cutover

Two `doppler run` behaviors are version-dependent; confirm them once on the
pinned CLI (they hold for v3.76.0):

- **DB precedence:** with a `DATABASE_URL` set in the environment, `doppler run
  --preserve-env="DATABASE_URL" -- env | grep DATABASE_URL` shows the OS value,
  not a Doppler one.
- **Signal forwarding:** a `SIGTERM` to the container drains gunicorn gracefully
  (the CLI forwards signals to the child; `--forward-signals` is set explicitly).

## Rollback

Unset `DOPPLER_TOKEN` in the DO dashboard (and, if you removed them in step 5,
re-add the plain env vars) and redeploy. The entrypoint falls back to plain env.
No image rebuild needed.

## Day-2 operations

- **Ad-hoc container commands** (e.g. `flask shell`, a backfill script) will NOT
  have secrets once the plain env vars are removed — run them through Doppler:
  `doppler run -- flask shell` (locally) or exec into the container and prefix the
  command with `doppler run --`.
- **Token rotation:** generate a new read-only service token in Doppler → update
  `DOPPLER_TOKEN` in DO → redeploy → revoke the old token.
- **Doppler outage resilience:** `doppler run` keeps an encrypted fallback cache
  by default, so a transient Doppler API failure at boot reads the last-known
  secrets instead of failing. `--no-fallback` disables this if ever needed.
- **Adding a new config var:** add it to Doppler (`dev` + `prd`) and to the
  `.env.example` inventory; no code change beyond the usual `os.getenv` read.
