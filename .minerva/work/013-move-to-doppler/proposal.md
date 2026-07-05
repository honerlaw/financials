# 013 — Move configuration to Doppler

## Status

Shipped (2026-07-05)

## Goal

Make Doppler the single source of truth for application configuration and
secrets, replacing ad-hoc environment variables set in the DigitalOcean App
Platform dashboard and the local `.env`. The cutover must be **staged and
zero-downtime** (the same image boots with or without Doppler), and must not
fight DO's managed-database binding.

## Why

Config today is scattered: ~17 values read via `os.getenv` in `app/__init__.py`,
set by hand in the DO dashboard for prod and in a gitignored `.env` locally, with
no access control, audit trail, or single place to rotate a leaked key. Doppler
gives one source of truth with versioning and per-environment configs. Because
the app already reads everything through `os.getenv`, Doppler only has to
*populate the environment* — so the application code does not change at all; the
work is deployment plumbing + a migration runbook.

## Scope note (what the PR delivers vs. the manual cutover)

The PR ships the **repo plumbing + a runbook**. The live migration completes via
**manual, user-side steps the agent cannot perform**: creating the Doppler
project/configs, populating secret values, minting the service token, and editing
the DO dashboard. Success criteria below are written in terms of what the PR can
actually prove (image builds, entrypoint works in both modes, docs are accurate,
no app regression), not "migration complete."

## Approach

Chosen: **hybrid + backward-compatible entrypoint** (approach A). Rejected:
(B) full Doppler including the DB URLs with a hard cutover — loses DO's managed-DB
auto-binding/rotation and makes deploy a breaking change with no fallback; (C) a
native DO↔Doppler secret-sync integration — does not exist for DO App Platform
(Doppler's first-class syncs target AWS/GCP/Vercel/etc.), so the CLI-in-image path
is the provider-agnostic mechanism.

### What goes in Doppler vs. what stays

- **In Doppler** (all app config + secrets): `SECRET_KEY`, `APP_PASSWORD`,
  `PLAID_CLIENT_ID`, `PLAID_SECRET`, `PLAID_ENV`, `OPENROUTER_API_KEY`,
  `OPENROUTER_MODEL`, `OPENROUTER_BASE_URL`, `CHAT_MAX_ITERATIONS`,
  `CHAT_QUERY_ROW_LIMIT`, `CHAT_MODELS`, `TWILIO_ACCOUNT_SID`,
  `TWILIO_AUTH_TOKEN`, `TWILIO_FROM_NUMBER`, `BUDGET_ALERT_RECIPIENTS`.
- **Stays out of Doppler — documented exception:** `DATABASE_URL` and
  `DATABASE_ADMIN_URL` remain injected by DO's managed-database binding. This is
  a deliberate exception to "single source of truth" because DO's binding also
  handles connection-string rotation; moving it into Doppler would trade that
  away. **This exception is called out prominently in the runbook so a future
  engineer "finishing the migration" does not move `DATABASE_URL` into Doppler.**
- **Bootstrap secret:** one `DOPPLER_TOKEN` (a read-only, config-scoped service
  token) lives in the DO dashboard; it is the only secret DO still holds.

### Why the hybrid is safe (resolved from Doppler docs, not assumed)

- **`DATABASE_URL` precedence:** verified against CLI **v3.76.0** — `doppler run`
  **overrides** existing OS env vars by default (`--preserve-env` defaults to
  `"false"`). So the entrypoint explicitly passes
  `--preserve-env="DATABASE_URL,DATABASE_ADMIN_URL"`, handing precedence back to
  the OS values for exactly the DB URLs. DO's binding-injected `DATABASE_URL`
  (and the shell-level `DATABASE_ADMIN_URL` override) therefore win even if
  someone later adds a `DATABASE_URL` to Doppler. Because this default is
  version-dependent, the CLI is **pinned** and the flag makes the intent explicit
  rather than relying on a default.
- **Graceful shutdown:** the Doppler CLI **forwards container signals
  (SIGTERM/SIGINT) to the child process**, so `exec doppler run -- gunicorn`
  preserves the drain-on-deploy behavior DO relies on for zero-downtime — the
  reason `exec` is used today.

### Repo changes

1. **`Dockerfile`** — install the Doppler CLI from its **signed apt repo**
   (not `curl | sh`), **version-pinned** via a build `ARG DOPPLER_CLI_VERSION`,
   cleaning apt lists to keep the slim image small.
2. **`entrypoint.sh`** — POSIX-`sh`-safe wrapper that runs the two commands
   (`flask db upgrade`, then `exec gunicorn …`) through `doppler run --` **only
   when `DOPPLER_TOKEN` is set and the `doppler` binary is present**, else plain.
   Uses a shell **function** (`run_with_secrets() { … "$@"; }`) — not an unquoted
   `$RUN` string — to avoid word-splitting (SC2086). **Logs which mode was
   chosen** (`[entrypoint] secrets via doppler run` vs `[entrypoint] DOPPLER_TOKEN
   unset — plain environment`) so a misconfiguration is never silent. Uses
   `doppler run --fallback` (encrypted local cache) so a Doppler API blip at boot
   doesn't hard-fail a restart. The existing
   `DATABASE_URL="${DATABASE_ADMIN_URL:-$DATABASE_URL}"` override is preserved.
3. **`doppler.yaml`** — project/config mapping for local `doppler setup`.
4. **`.env.example`** — reframed: documents that these values live in Doppler and
   how local dev works; retains the full var list as the canonical inventory of
   what a Doppler config must contain.
5. **`docs/doppler-migration.md`** — the runbook: create project/configs,
   populate vars, mint the read-only config-scoped service token, set
   `DOPPLER_TOKEN` in DO, the **staged cutover** (add Doppler → verify → remove DO
   vars one environment at a time), **rollback** (unset `DOPPLER_TOKEN` → plain
   env), the DB-URL exception, running **ad-hoc container commands** through
   `doppler run`, and **token rotation**.
6. **App code (`os.getenv`)** — unchanged.
7. **Local dev** — **unchanged and optional**: `python-dotenv` + `.env` keep
   working (the entrypoint falls back to plain env, and `os.getenv` is untouched).
   Developers *may* opt into `doppler run -- flask run`; they are not required to.

## Success criteria

- [ ] `docker build` succeeds with the pinned Doppler CLI installed
  (`doppler --version` runs in the image). If Docker is unavailable in the work
  environment, the apt-repo install snippet is validated against Doppler's
  documented method and that limitation is stated explicitly.
- [ ] `entrypoint.sh` passes `sh -n` (POSIX syntax) and `shellcheck` clean of
  SC2086; **both branches are exercised** with a stubbed `doppler` on `PATH`:
  with `DOPPLER_TOKEN` set → command runs under `doppler run --`; unset → runs
  plain. Both log the chosen mode.
- [ ] Backward compatibility: the existing app test suite still passes (no code
  change; `os.getenv` untouched), and the plain-env boot path is unchanged.
- [ ] `docs/doppler-migration.md` exists and documents: the full var inventory,
  the `DATABASE_URL` hybrid exception, staged cutover, rollback, ad-hoc commands,
  and token rotation. `.env.example` reframed; `doppler.yaml` present.

## Open Questions / operational (out of code scope)

- The Doppler account/project/token creation and DO dashboard edits are manual;
  the PR cannot complete or fully verify the live cutover.
- Exact `doppler run` env-precedence and signal-forwarding must be re-verified
  against the **pinned CLI version** during the manual cutover (documented as a
  runbook gate) — this environment has no Doppler CLI to exercise them live.
- Whether to ever fold the DB URLs into Doppler too — deferred (see the
  documented exception).

## Related

- [[budget-alert-notifier]] — added the `TWILIO_*` / `BUDGET_ALERT_RECIPIENTS`
  config now routed through Doppler; also relies on the same `os.getenv` +
  `--workers 1` deploy shape.
