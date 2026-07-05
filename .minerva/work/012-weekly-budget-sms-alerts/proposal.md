# 012 — Weekly-budget SMS alerts

## Status

Draft

## Goal

After every transaction sync, send an SMS to each configured recipient **once
per Sun–Sat week for each newly-crossed 50% / 75% / 100% threshold** of the
current week's spend against the $1,000 weekly budget. Each text states the
dollars spent so far. Recipients are the household (you + your wife).

## Why

Work unit 010 already computes and displays weekly-budget progress on the
dashboard, but it is **passive** — you only see it if you open the app.
Proactively texting both spouses the moment spending crosses a milestone turns
the tracker into an active guardrail, early enough in the week to course-correct.
The spend math (`app/spending.py`) is already built and unit-tested, so this is a
thin, well-grounded notification layer on top of a solved calculation.

## Approach

Chosen: the official `twilio` SDK behind a thin injectable wrapper (approach B).
Rejected: (A) a hand-rolled httpx Twilio client mirroring `openrouter.py` — zero
new deps but chosen against per user preference for the vendor SDK's ergonomics
and typed errors; (C) record crossings during sync and send from a separate
cron — rejected because it reintroduces latency the near-real-time requirement
rules out.

### Configuration (env)

Four new vars, wired into `create_app` alongside the `OPENROUTER_*` block and
documented in `.env.example`:

- `TWILIO_ACCOUNT_SID`, `TWILIO_AUTH_TOKEN`, `TWILIO_FROM_NUMBER`
- `BUDGET_ALERT_RECIPIENTS` — comma-separated E.164 numbers, parsed exactly like
  `CHAT_MODELS` (split on comma, strip, drop empties).

**Kill-switch / deploy-inert semantics (soft-disable):** the feature is a clean
no-op unless **all four** vars are set to non-empty values. Missing config does
**not** hard-fail startup (unlike `SECRET_KEY`/`APP_PASSWORD`) — it simply
disables alerting. This is the intended safety valve: the code can ship to
production inert (no recipients configured → nothing is ever sent) and be
verified against real spend data before any number is wired up.

### Model

New table `budget_alerts` via `BudgetAlert`:

- `id`, `week_start` (Date, the Sunday), `threshold` (Integer: 50/75/100),
  `recipient` (String), `sent_at` (DateTime tz).
- **Unique constraint `(week_start, threshold, recipient)`** — per-recipient
  grain, so one recipient's send failure never blocks the other's alert and
  never produces a duplicate. This is also the cross-process dedup backstop
  (see Concurrency).
- One Alembic migration.

### Pure logic (`app/spending.py`)

Add `week_spend(transactions, today) -> Decimal` — sums `is_spend` amounts for
the Sun–Sat week containing `today`, reusing the existing `is_spend` /
`week_start`. Reference-date-as-parameter, matching the module's existing
deterministic-test discipline ([[004-pattern-seed-relative-dates-in-time-sensitive-tests]]).

### Notifier (`app/notifications.py`, new)

- **Pure** `newly_crossed(pct, already_sent) -> [thresholds]` — sorted subset of
  `(50, 75, 100)` where `t <= pct and t not in already_sent`.
- `TwilioSender` — thin injectable wrapper over the SDK
  (`Client(sid, token).messages.create(to, from_, body)`), exposing
  `.send(to, body)`, constructed from config with a **send timeout** so a hung
  Twilio call cannot pile up sync threads. Tests inject a fake; the SDK is never
  called in tests.
- `send_budget_alerts(session, today, config, sender=None)`:
  1. **No-op** unless all four config vars are set.
  2. Query **all** institutions' transactions (`removed=False`) for the current
     Sun–Sat week — a **household total**, no institution filter — and compute
     `spent = week_spend(...)`, `pct = int(spent / WEEKLY_BUDGET * 100)`.
  3. For each recipient: load already-sent thresholds for this `week_start`;
     `newly = newly_crossed(pct, already)`; for each threshold, **send the SMS,
     then insert the `BudgetAlert` row on success**. A failed send leaves the
     row unwritten → retried on the next sync.
  4. On the insert, **catch `IntegrityError`** (a concurrent claim won the race)
     and skip — belt-and-suspenders on top of the lock below.

### Concurrency

`sync_all_institutions()` runs from a 7am APScheduler cron **and** from three
Flask routes that each spawn a background thread — `/api/sync` fires on **every
page load**. Two near-simultaneous loads → two threads → both could read "50%
not sent" and both text. Mitigation:

- The **entire body** of `send_budget_alerts` (all recipients, all Twilio calls,
  all inserts) runs under a **module-level `threading.Lock`**, fully serializing
  the check→send→insert across all sync threads in the process.
- This is correct because the app runs a **single gunicorn worker**
  (`entrypoint.sh: --workers 1`), which the in-process APScheduler *already*
  requires app-wide (multiple workers would run multiple schedulers). A code
  comment states this invariant explicitly.
- The DB unique constraint + caught `IntegrityError` is the cross-process
  backstop should that invariant ever change: it cannot prevent a duplicate
  *SMS*, but it prevents a duplicate *row* and short-circuits the redundant send.

### Hook (`app/sync.py`)

Call `send_budget_alerts(db.session, date.today(), current_app.config)` at the
**end of `sync_all_institutions()`** (once per run, after the institution loop),
wrapped in its own `try/except` logging via `current_app.logger.exception`. A
notification failure annotates the log but **never aborts the sync** and never
touches `SyncLog.error` — mirroring the non-fatal `_refresh_balances` pattern.

### Message

`"Budget alert: {pct}% of this week's $1,000 budget — ${spent:.0f} spent (week
of {Mon D})."` — a sensible default, trivially tunable.

## Success criteria

- [ ] `newly_crossed` unit-tested: crossing exactly at a threshold, below it, an
  already-sent set, a multi-cross jump (`pct=105, already={}` → `[50, 75, 100]`),
  and an empty result when nothing new crosses.
- [ ] `week_spend` unit-tested: sums only current-week `is_spend` transactions,
  excludes `TRANSFER`/`LOAN_PAYMENTS` and negative amounts, respects the Sun–Sat
  boundary.
- [ ] `send_budget_alerts` tested with a fake sender + in-memory DB:
  - sends once per `(threshold, recipient)` per week; a second sync the same week
    sends nothing (idempotent);
  - clean no-op when any of the four config vars is unset (incl. partial config);
  - a recipient whose send raises gets **no** row (retried next call);
  - a raising sender **never aborts** the caller.
- [ ] Concurrency test: two threads invoking `send_budget_alerts` against a
  shared session + fake sender result in **exactly one** send per threshold.
- [ ] Alembic migration applies cleanly (`flask db upgrade` on a fresh DB).
- [ ] `.env.example` documents the four new vars; `requirements.txt` adds
  `twilio`.

## Open Questions

- **Deliverability vs. "sent":** the row is written on Twilio API-**accept**, not
  carrier delivery. US A2P 10DLC registration of `TWILIO_FROM_NUMBER` is an
  **operational prerequisite** (unregistered numbers are silently filtered) —
  out of code scope, but noted so "works in tests" is not mistaken for "reaches a
  phone."
- **Headless by design:** unlike prior units this feature has **no UI surface**
  (no alert history / toggle in-app). Acknowledged scope decision for a personal
  app; a settings surface could be a future unit.
- Exact message wording (a default is chosen above).

## Related

- [[008-decision-dashboard-spend-and-weekly-budget]] — the weekly-budget math
  and spend definition this reuses.
- [[004-pattern-seed-relative-dates-in-time-sensitive-tests]] — why the new pure
  functions take `today` as a parameter.
- [[007-decision-plaid-reconnect-update-mode]] — sibling non-fatal side-effect
  inside the sync path (`_refresh_balances`).
