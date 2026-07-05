# Scratchpad — 012-weekly-budget-sms-alerts

## Balanced decisions 2026-07-05

- [reviewed — folded] scope check: single unit (Skeptic verdict `revise` but explicitly "keep single unit — no clean independently-shippable split boundary"; folded its precision points — dedup key already per-recipient, added explicit kill-switch/deploy-inert semantics, explicit non-fatal error path, acknowledged headless-no-UI scope decision).
- [reviewed — folded] approach: option B (twilio SDK) (Skeptic verdict `revise` but "SDK choice, schema, hook placement sound"; folded — made `threading.Lock` scope explicit over the whole body, added `IntegrityError` cross-process backstop, added `TwilioSender` send-timeout, added concurrency + multi-cross + partial-config tests to success criteria, flagged A2P 10DLC "sent≠delivered" in Open Questions). Rejected A (hand-rolled httpx — user preferred SDK) and C (cron-decoupled — reintroduces latency).
- [decided] whole-proposal soundness: sound (solo gate) — single new surface is 4 env vars + one internal function; no cross-cutting contract requiring escalation.

## Implementation notes 2026-07-05

- Added `week_spend` (app/spending.py), `BudgetAlert` model (app/models.py), `app/notifications.py` (pure `newly_crossed` + `TwilioSender` + `send_budget_alerts` under module lock), sync hook `_send_budget_alerts_safe` (app/sync.py), 4 config vars (app/__init__.py), `.env.example` + `requirements.txt` (twilio), migration `b7f3a9c1d2e4`.
- Full suite: **179 passed** (incl. 5 `newly_crossed`, 3 `week_spend`, 8 notifier/concurrency, 2 sync-hook tests).
- Migration verified in isolation on sqlite (upgrade builds `budget_alerts` w/ 3-col unique constraint; downgrade drops it). NOTE: `flask db upgrade` cannot run end-to-end on sqlite because the **pre-existing** `00a2889ed2af` GRANT migration is Postgres-only (no dialect guard) — not a regression; prod migrates on Postgres. Verified chain head via `flask db history`.
- twilio not pip-installed locally; import is lazy inside `TwilioSender`, so tests (which inject fakes) never touch it.
