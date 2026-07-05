"""Weekly-budget SMS alerts.

After each sync (``app.sync.sync_all_institutions``) we text every configured
recipient once per Sun–Sat week for each newly-crossed 50/75/100% threshold of
the current week's household spend against ``WEEKLY_BUDGET``. The spend and
threshold math is pure and unit-tested (``spending.week_spend`` /
``newly_crossed``); the Twilio send and the ``BudgetAlert`` writes are the impure
shell.

Feature gating (soft-disable): the notifier is a clean no-op unless all four of
``TWILIO_ACCOUNT_SID`` / ``TWILIO_AUTH_TOKEN`` / ``TWILIO_FROM_NUMBER`` /
``BUDGET_ALERT_RECIPIENTS`` are set. Missing config never raises — the app can
ship inert and be verified against real spend before any number is wired up.

Concurrency: ``sync_all_institutions`` runs from a 7am APScheduler cron AND from
a background thread per ``/api/sync`` (fired on every page load), so two syncs
can overlap. The ENTIRE body of ``send_budget_alerts`` runs under a module-level
``threading.Lock``, which fully serializes check→send→record because the app
runs a SINGLE gunicorn worker (``entrypoint.sh: --workers 1``) — an invariant the
in-process APScheduler already depends on. The ``BudgetAlert`` unique constraint
(plus the caught ``IntegrityError``) is the cross-process backstop: it cannot
un-send a duplicate SMS, but it prevents a duplicate row and short-circuits the
redundant send if that single-worker invariant ever changes.
"""
import threading
from datetime import timedelta

from flask import current_app
from sqlalchemy.exc import IntegrityError

from app.models import BudgetAlert, Transaction
from app.spending import WEEKLY_BUDGET, week_spend, week_start

THRESHOLDS = (50, 75, 100)

# Serializes send_budget_alerts across concurrent sync threads. Correct only
# under a single worker process (see module docstring); the DB unique constraint
# is the cross-process backstop.
_send_lock = threading.Lock()


def newly_crossed(pct, already_sent):
    """Thresholds at/under ``pct`` not already alerted, ascending.

    ``pct`` is the integer percent of budget spent; ``already_sent`` is the set
    of thresholds already texted this week for one recipient.
    """
    already = set(already_sent)
    return [t for t in THRESHOLDS if t <= pct and t not in already]


class TwilioSender:
    """Thin injectable wrapper over the twilio SDK. Tests inject a fake."""

    def __init__(self, account_sid, auth_token, from_number, timeout=10):
        from twilio.http.http_client import TwilioHttpClient
        from twilio.rest import Client
        # Bound the HTTP call so a hung Twilio request can't hold the module lock
        # (and thus pile up sync threads) indefinitely.
        self._client = Client(
            account_sid, auth_token,
            http_client=TwilioHttpClient(timeout=timeout),
        )
        self._from = from_number

    def send(self, to, body):
        self._client.messages.create(to=to, from_=self._from, body=body)


def _recipients(config):
    """Parse BUDGET_ALERT_RECIPIENTS like CHAT_MODELS: split, strip, drop empty."""
    raw = config.get('BUDGET_ALERT_RECIPIENTS') or ''
    return [r.strip() for r in raw.split(',') if r.strip()]


def _sender_from_config(config):
    """Build a TwilioSender when fully configured, else None (feature disabled)."""
    sid = config.get('TWILIO_ACCOUNT_SID')
    token = config.get('TWILIO_AUTH_TOKEN')
    from_number = config.get('TWILIO_FROM_NUMBER')
    if not (sid and token and from_number):
        return None
    return TwilioSender(sid, token, from_number)


def _message(pct, spent, ws):
    return (
        f"Budget alert: {pct}% of this week's ${int(WEEKLY_BUDGET):,} budget "
        f"— ${spent:,.0f} spent (week of {ws.strftime('%b %-d')})."
    )


def send_budget_alerts(session, today, config, sender=None):
    """Text each recipient for every newly-crossed weekly-budget threshold.

    No-op unless recipients AND Twilio credentials are configured. A row is
    recorded only after a successful send, so a failed send is retried next sync.
    Individual send failures are logged and skipped; they never propagate. Runs
    under the module lock (see module docstring).
    """
    recipients = _recipients(config)
    if not recipients:
        return
    if sender is None:
        sender = _sender_from_config(config)
    if sender is None:
        return

    with _send_lock:
        ws = week_start(today)
        week_end_exclusive = ws + timedelta(days=7)
        txns = (
            session.query(Transaction)
            .filter(Transaction.removed.is_(False))
            .filter(Transaction.date >= ws, Transaction.date < week_end_exclusive)
            .all()
        )
        spent = week_spend(txns, today)
        pct = int(spent / WEEKLY_BUDGET * 100) if WEEKLY_BUDGET else 0

        for recipient in recipients:
            already = [
                row.threshold for row in session.query(BudgetAlert)
                .filter(BudgetAlert.week_start == ws,
                        BudgetAlert.recipient == recipient).all()
            ]
            for threshold in newly_crossed(pct, already):
                try:
                    sender.send(recipient, _message(pct, spent, ws))
                except Exception:
                    current_app.logger.exception(
                        'budget alert send failed (recipient=%s threshold=%s)',
                        recipient, threshold,
                    )
                    continue  # leave unrecorded → retried next sync
                session.add(BudgetAlert(
                    week_start=ws, threshold=threshold, recipient=recipient,
                ))
                try:
                    session.commit()
                except IntegrityError:
                    # A concurrent claim already recorded this (week, threshold,
                    # recipient); drop our duplicate row.
                    session.rollback()
