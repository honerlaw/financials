# Configuration via Doppler: hybrid + backward-compatible entrypoint

**Date**: 2026-07-05
**Type**: decision
**Summary**: Config/secrets managed via Doppler with a backward-compatible entrypoint — doppler run only when DOPPLER_TOKEN is set (else plain env); DB URLs stay from DO's managed binding, protected by --preserve-env; CLI pinned; fail-closed
**Context**: .minerva/work/013-move-to-doppler

## Context

Config was scattered: ~17 values read via `os.getenv` in `app/__init__.py`, set by
hand in the DigitalOcean App Platform dashboard for prod and in a local `.env`.
Unit 013 made **Doppler** the single source of truth. Because the app reads
everything through `os.getenv`, Doppler only has to *populate the environment* —
**no application code changed**; the work is deployment plumbing + a runbook
(`docs/doppler-migration.md`).

## Decisions

1. **Doppler CLI baked into the image, not a native integration.** DO App
   Platform has no first-class Doppler sync (Doppler's native syncs target
   AWS/GCP/Vercel/etc.), so the provider-agnostic path is the CLI in the image
   (installed from Doppler's **GPG-signed apt repo**, not `curl|sh`) and launched
   via `doppler run`. The CLI version is **pinned** (`ARG DOPPLER_CLI_VERSION`)
   because `doppler run` env-precedence behaviour is version-dependent.

2. **Backward-compatible, conditional entrypoint (staged, reversible cutover).**
   `entrypoint.sh` uses `doppler run` **only when `DOPPLER_TOKEN` is set and the
   `doppler` binary is present**, else it runs the commands on plain env. The same
   image boots both ways, so cutover is: deploy image (plain) → set `DOPPLER_TOKEN`
   (Doppler takes over) → remove the old DO dashboard vars; rollback is just
   unsetting the token. The entrypoint **logs which mode it chose**. It is
   **fail-closed**: `doppler run` exits non-zero on a bad/expired token and
   `set -e` aborts boot (the app never starts on empty config).

3. **Hybrid — DB URLs stay out of Doppler, protected with `--preserve-env`.**
   `DATABASE_URL`/`DATABASE_ADMIN_URL` remain injected by DO's managed-database
   binding (which also rotates them). Since `doppler run` **overrides** existing
   OS env vars by default (`--preserve-env` defaults to `"false"`, verified on CLI
   v3.76.0 — the opposite of some older community guidance), the entrypoint passes
   `--preserve-env="DATABASE_URL,DATABASE_ADMIN_URL"` so the DO-injected values win
   even if a stray `DATABASE_URL` is added to Doppler. This is a deliberate,
   documented exception to "single source of truth."

4. **Signals + one bootstrap secret.** `--forward-signals` (default true for
   non-TTY) is set explicitly so the CLI forwards SIGTERM to gunicorn for
   graceful, zero-downtime shutdown when it is PID 1. `DOPPLER_TOKEN` (a
   read-only, config-scoped service token) is the only secret still held in DO.

## Implementation notes / gotchas

- **`exec` cannot run a shell function.** The migration runs through a
  `run_with_secrets()` wrapper, but the long-running server must `exec` to be PID
  1 with correct signal handling — so the final `exec doppler run -- gunicorn …`
  is branched inline in each mode. Consequence: the doppler flags are duplicated
  between the function and the exec line (commented "keep in sync") — a known
  low-severity drift risk, inherent to POSIX `sh`.
- **`DATABASE_ADMIN_URL` override is subshell-scoped** to the `flask db upgrade`
  step so it never leaks to gunicorn (which must use the regular `DATABASE_URL`).
- Local dev is unchanged/optional: `python-dotenv` + `.env` still work; a dev may
  opt into `doppler run -- flask run` via `doppler setup` (`doppler.yaml`).

## Out of scope / operational

- The live migration completes via **manual, user-side** steps (create Doppler
  project/configs, populate values, mint the token, edit the DO dashboard) — the
  PR ships the plumbing + runbook, not the completed cutover.
- Precedence and signal-forwarding should be **re-verified against the pinned CLI
  version** during cutover (a runbook gate).

## Related

- [[010-decision-budget-alert-notifier]] — see also
  contributed the `TWILIO_*` / `BUDGET_ALERT_RECIPIENTS` config now routed through Doppler; shares the `os.getenv` + `--workers 1` deploy shape.
- [[016-decision-daily-digest-notifier]] — see also
- [[017-pattern-migration-chain-is-postgres-only]] — see also
- [[024-decision-digest-net-worth]] — see also
