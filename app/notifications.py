"""Daily digest SMS — weekly-budget status plus every account balance.

Once a day, right after the 7am sync (``app.sync.run_daily_sync``), every
configured recipient is texted one message: where the current Sun–Sat week's
household spend stands against ``WEEKLY_BUDGET``, and the current balance of
each linked account. The message building is pure and unit-tested
(``digest_body`` and friends); the Twilio send and the ``DailyDigest`` writes are
the impure shell.

Cadence: exactly one text per recipient per calendar day, deduped on
``(sent_date, recipient)``. Nothing here is threshold-driven — a quiet week
still produces a morning text, which is the point. "Today" is the date in
``APP_TIMEZONE`` (see ``app/localtime.py``), not UTC's date.

There is a second, manual trigger: ``send_digest_now`` builds the identical
message on demand (the dashboard's "Text me this" button). It deliberately
neither reads nor writes ``DailyDigest``, so a press always sends and never
interacts with the scheduled digest in either direction.

Feature gating (soft-disable): the notifier is a clean no-op unless all four of
``TWILIO_ACCOUNT_SID`` / ``TWILIO_AUTH_TOKEN`` / ``TWILIO_FROM_NUMBER`` /
``BUDGET_ALERT_RECIPIENTS`` are set. Missing config never raises — the app can
ship inert and be verified against real spend before any number is wired up.
(``BUDGET_ALERT_RECIPIENTS`` keeps its unit-012 name on purpose: the secret
lives in the shared Doppler project, where renaming is cross-repo churn.)

Concurrency: dispatch now happens only from the single 7am job (``max_instances=1``),
not from the per-page-load sync, so overlap is not expected. The body still runs
under a module-level ``threading.Lock`` as defence in depth, which fully
serializes check→send→record because the app runs a SINGLE gunicorn worker
(``entrypoint.sh: --workers 1``) — an invariant the in-process APScheduler
already depends on. The ``DailyDigest`` unique constraint (plus the caught
``IntegrityError``) is the cross-process backstop: it cannot un-send a duplicate
SMS, but it prevents a duplicate row and short-circuits the redundant send if
that single-worker invariant ever changes.
"""
import threading
from datetime import timedelta

from flask import current_app
from sqlalchemy.exc import IntegrityError

from app.models import Account, DailyDigest, Institution, Transaction
from app.spending import WEEKLY_BUDGET, week_spend, week_start

# Serializes send_daily_digest across any concurrent callers. Correct only
# under a single worker process (see module docstring); the DB unique constraint
# is the cross-process backstop.
_send_lock = threading.Lock()


def budget_line(spent, budget=WEEKLY_BUDGET):
    """``Budget: $750 of $1,000 (75%) — $250 left`` / ``… (124%) — $240 OVER``.

    ``pct`` truncates like the dashboard tracker, so the text and the UI always
    agree. Percent keeps climbing past 100 rather than clamping — being 124% of
    budget is the thing worth knowing.
    """
    pct = int(spent / budget * 100) if budget else 0
    remaining = budget - spent
    tail = (f"${remaining:,.0f} left" if remaining >= 0
            else f"${-remaining:,.0f} OVER")
    return f"Budget: ${spent:,.0f} of ${budget:,.0f} ({pct}%) — {tail}"


def account_line(institution_name, account_name, mask, balance, stale=False):
    """``Truist · Checking ••3390: $4,880.02`` (balance ``—`` when unknown).

    The balance is printed exactly as the dashboard prints it — raw
    ``current_balance``, no sign flipping — so a card's number never reads one
    way in the app and another way in the text.

    ``stale`` flags an institution that is no longer syncing (it needs a Plaid
    reconnect). Its balance is frozen at the last successful sync, and a text is
    a worse place than the dashboard to quietly show a wrong number — there is
    no reconnect banner next to it.
    """
    label = f'{institution_name} · {account_name}'
    if mask:
        label += f' ••{mask}'
    amount = '—' if balance is None else f'${balance:,.2f}'
    suffix = ' (reconnect needed)' if stale else ''
    return f'{label}: {amount}{suffix}'


def digest_body(today, spent, accounts, budget=WEEKLY_BUDGET):
    """The full SMS text.

    ``accounts`` is an iterable of ``(institution_name, account_name, mask,
    balance[, stale])`` tuples — plain data, not ORM rows, so this stays pure.
    """
    lines = [
        f"Good morning — {today.strftime('%a %b %-d')}",
        '',
        budget_line(spent, budget),
        f"Week of {week_start(today).strftime('%b %-d')}",
        '',
        'Balances',
    ]
    account_lines = [account_line(*a) for a in accounts]
    lines.extend(account_lines or ['No linked accounts.'])
    return '\n'.join(lines)


class TwilioSender:
    """Thin injectable wrapper over the twilio SDK. Tests inject a fake."""

    def __init__(self, account_sid, auth_token, from_number, timeout=10):
        from twilio.http.http_client import TwilioHttpClient
        from twilio.rest import Client
        # Bound the HTTP call so a hung Twilio request can't hold the module lock
        # (and thus pile up callers) indefinitely.
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


def _week_spent(session, today):
    """This week's household spend — no institution filter, same math as the dashboard."""
    ws = week_start(today)
    txns = (
        session.query(Transaction)
        .filter(Transaction.removed.is_(False))
        .filter(Transaction.date >= ws, Transaction.date < ws + timedelta(days=7))
        .all()
    )
    return week_spend(txns, today)


def _account_balances(session):
    """``(institution, account, mask, balance, stale)`` for every account.

    Ordered by institution then account name, matching the dashboard's account
    cards. Accounts with a null balance are still listed, so a freshly linked
    account shows up in the digest immediately. ``stale`` marks an institution
    that ``sync_all_institutions`` skips (anything but ``active``), whose
    balances stopped updating at its last successful sync.
    """
    rows = (
        session.query(
            Institution.name, Account.name, Account.mask,
            Account.current_balance, Institution.status,
        )
        .select_from(Account)
        .join(Institution, Institution.id == Account.institution_id)
        .order_by(Institution.name, Account.name)
        .all()
    )
    return [(inst, acct, mask, balance, status != 'active')
            for inst, acct, mask, balance, status in rows]


def send_daily_digest(session, today, config, sender=None):
    """Text each recipient one digest for ``today``, at most once per day.

    No-op unless recipients AND Twilio credentials are configured, and unless at
    least one recipient is still un-texted today. A row is recorded only after a
    successful send, so a failed send is retried on the next dispatch.
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
        already = {
            row.recipient for row in session.query(DailyDigest)
            .filter(DailyDigest.sent_date == today).all()
        }
        pending = [r for r in recipients if r not in already]
        if not pending:
            return

        body = digest_body(
            today, _week_spent(session, today), _account_balances(session),
        )

        for recipient in pending:
            try:
                sender.send(recipient, body)
            except Exception:
                current_app.logger.exception(
                    'daily digest send failed (recipient=%s)', recipient,
                )
                continue  # leave unrecorded → retried next dispatch
            session.add(DailyDigest(sent_date=today, recipient=recipient))
            try:
                session.commit()
            except IntegrityError:
                # A concurrent claim already recorded this (date, recipient);
                # drop our duplicate row.
                session.rollback()
            except Exception:
                # The SMS already went out but recording it failed (e.g. a
                # dropped connection). Roll back so the session isn't left
                # poisoned for the remaining recipients, and keep going. The
                # unrecorded row means the next dispatch *may* re-text this
                # recipient — an acceptable rare duplicate, preferable to
                # silently dropping the day's digest.
                session.rollback()
                current_app.logger.exception(
                    'daily digest recorded-send failed to persist '
                    '(recipient=%s)', recipient,
                )


def send_digest_now(session, today, config, sender=None):
    """Send the digest immediately to every recipient, ignoring the daily dedup.

    The on-demand counterpart to ``send_daily_digest``: same recipients, same
    message, but a press always sends. It reads no ``DailyDigest`` row (so it
    works after today's scheduled digest already went out) and writes none (so
    it never suppresses tomorrow's). The lock is shared with the scheduled path
    so a press cannot interleave with a concurrent 7am dispatch.

    Unlike the scheduled path — a fire-and-forget side-effect that only logs —
    this reports back, because a button has to say what happened::

        {'configured': bool, 'sent': [recipient, ...], 'failed': [recipient, ...]}

    ``configured`` is False when the feature is soft-disabled (no recipients, or
    incomplete Twilio credentials); the caller surfaces that as a real message
    rather than a silent success.
    """
    recipients = _recipients(config)
    if not recipients:
        return {'configured': False, 'sent': [], 'failed': []}
    if sender is None:
        sender = _sender_from_config(config)
    if sender is None:
        return {'configured': False, 'sent': [], 'failed': []}

    with _send_lock:
        body = digest_body(
            today, _week_spent(session, today), _account_balances(session),
        )
        sent, failed = [], []
        for recipient in recipients:
            try:
                sender.send(recipient, body)
            except Exception:
                current_app.logger.exception(
                    'manual digest send failed (recipient=%s)', recipient,
                )
                failed.append(recipient)
                continue  # one recipient's failure must not stop the rest
            sent.append(recipient)
        return {'configured': True, 'sent': sent, 'failed': failed}
