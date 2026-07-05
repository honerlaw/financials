#!/bin/sh
set -e

# Inject secrets via Doppler when configured, otherwise run on plain environment
# variables. Doppler is used only when a service token is present AND the CLI is
# installed, so the same image boots with or without Doppler — a staged,
# reversible cutover (unset DOPPLER_TOKEN to fall back to plain env).
#
# doppler run flags (verified against CLI v3.76.0):
#   --preserve-env="DATABASE_URL,DATABASE_ADMIN_URL"
#       The DB connection strings are injected by DigitalOcean's managed-database
#       binding, NOT Doppler (see docs/doppler-migration.md). Doppler OVERRIDES
#       existing env vars by default (--preserve-env defaults to "false"), so we
#       explicitly hand precedence back to the OS values for these two —
#       otherwise a stray DATABASE_URL added to Doppler could silently point the
#       app at the wrong database.
#   --forward-signals
#       Forward SIGTERM/SIGINT to the child so gunicorn drains in-flight requests
#       on deploy/restart (zero-downtime). Defaults to true for non-TTY stdout;
#       set explicitly so it never depends on the runtime context.
#   --silent
#       Suppress Doppler's info banner in production logs.
if [ -n "${DOPPLER_TOKEN:-}" ] && command -v doppler >/dev/null 2>&1; then
    echo "[entrypoint] secrets via doppler run ($(doppler --version))"
    DOPPLER_ON=1
    run_with_secrets() {
        doppler run \
            --preserve-env="DATABASE_URL,DATABASE_ADMIN_URL" \
            --forward-signals --silent -- "$@"
    }
else
    echo "[entrypoint] DOPPLER_TOKEN unset or doppler CLI missing — using plain environment"
    DOPPLER_ON=0
    run_with_secrets() { "$@"; }
fi

# Apply DB migrations (short-lived). DATABASE_ADMIN_URL (if set) overrides
# DATABASE_URL for the upgrade only; scoped to this subshell so the override
# never leaks to the gunicorn process, which must use the regular DATABASE_URL.
(
    export DATABASE_URL="${DATABASE_ADMIN_URL:-$DATABASE_URL}"
    run_with_secrets flask --app wsgi db upgrade
)

# Start the server with exec so it becomes PID 1 and receives signals directly.
# `exec` cannot run a shell function, so the doppler prefix is branched inline
# here (keep the flags in sync with run_with_secrets above). In the Doppler path
# the CLI is PID 1 and forwards SIGTERM to gunicorn; in the plain path gunicorn
# is PID 1 itself.
if [ "$DOPPLER_ON" = 1 ]; then
    exec doppler run \
        --preserve-env="DATABASE_URL,DATABASE_ADMIN_URL" \
        --forward-signals --silent -- \
        gunicorn wsgi:app --bind 0.0.0.0:8080 --workers 1 --timeout 120
else
    exec gunicorn wsgi:app --bind 0.0.0.0:8080 --workers 1 --timeout 120
fi
