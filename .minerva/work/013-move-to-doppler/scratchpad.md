# Scratchpad — 013-move-to-doppler

## Balanced decisions 2026-07-05

- [reviewed — folded] scope check: single unit (both Skeptics agreed single-unit is sound; no independently-shippable boundary). Folded: (a) corrected a Skeptic false-alarm — it grepped stale local `main` and thought the `TWILIO_*`/`BUDGET_ALERT_RECIPIENTS` vars were fabricated; they exist on `origin/main` (unit 012, PR #13, just merged), so the worktree is branched off **origin/main** not local main; (b) framed success criteria as PR-provable (image builds, entrypoint both-branch, docs) rather than "migration complete".
- [reviewed — folded] approach: hybrid + backward-compatible entrypoint (both Skeptics: hybrid sound, correctly rejects B hard-cutover / C nonexistent DO integration). Folded: mode-logging in entrypoint; POSIX shell **function** wrapper instead of unquoted `$RUN` (SC2086); pinned signed apt-repo CLI install (not curl|sh); `doppler run --fallback` cache; local-dev unchanged/optional; ad-hoc-command + token-rotation + DB-exception runbook sections; explicit prominent "DB URLs stay out of Doppler" exception. Two high-severity unknowns resolved from Doppler docs rather than escalated: OS-env precedence protects DO's DATABASE_URL, and the CLI forwards SIGTERM (zero-downtime preserved) — both flagged for re-verify against the pinned CLI during cutover.
- [decided] whole-proposal soundness: sound (solo gate). Surface = deploy plumbing + docs, app code unchanged. entrypoint.sh is high-blast-radius but the change is backward-compatible + reversible and locally verifiable (sh -n, stubbed-doppler both-branch, docker build); no cross-cutting contract needing escalation.

## Implementation notes 2026-07-05

Files: Dockerfile (pinned Doppler CLI 3.76.0 via signed apt repo), entrypoint.sh (conditional doppler-run wrapper), doppler.yaml, .env.example (reframed), docs/doppler-migration.md (runbook). App code unchanged.

Verified against the REAL CLI (built a throwaway image, inspected `doppler run --help` on v3.76.0):
- **`docker build` succeeds** — pinned `doppler=3.76.0` resolves from the signed apt repo; full app image builds, `doppler --version`=v3.76.0, flask+twilio import.
- **entrypoint both branches** tested with stubbed binaries: DOPPLER_TOKEN set → wraps in `doppler run`; unset → plain. `dash -n` clean. Boot logs the chosen mode.
- **DB-override scoping**: `DATABASE_ADMIN_URL` reaches `flask db upgrade` but gunicorn gets the regular `DATABASE_URL` (subshell scoping verified).
- **fail-closed**: real `doppler run` with a bogus token → exit 1, wrapped command never runs.
- app test suite: **182 passed** (no code change).

Two mid-work corrections (implementation refinements within the approved approach, not divergences → handled inline):
1. **`--preserve-env` default is `"false"`** (Doppler OVERRIDES OS env by default) — opposite of the community-forum hint. Corrected the proposal's justification; the DB protection now comes from an explicit `--preserve-env="DATABASE_URL,DATABASE_ADMIN_URL"` flag (more robust than the hand-waved "OS wins by default"). `--forward-signals` default true (non-TTY) confirms graceful shutdown.
2. **`exec` cannot run a shell function** — first draft did `exec run_with_secrets gunicorn` (fails: `exec: run_with_secrets: not found`). Fixed by branching the final `exec` inline (doppler-run prefix in each branch) so gunicorn/doppler is PID 1 with correct signal handling; the function is used only for the non-exec migration.
