"""Daily digest SMS — budget status, recent weeks, card debt, yesterday's spend.

Once a day, right after the 7am sync (``app.sync.run_daily_sync``), every
configured recipient is texted one message: where the current Sun–Sat week's
household spend stands against ``WEEKLY_BUDGET``, what each of the four
completed weeks behind it totalled, the current balance of every linked credit
card and the debt they add up to, and what was bought yesterday — a count and
total, every purchase over $100, and spend by category. The message building
is pure and unit-tested (``digest_body`` and friends); the Twilio send and the
``DailyDigest`` writes are the impure shell.

Cadence: exactly one text per recipient per calendar day, deduped on
``(sent_date, recipient)``. Nothing here is threshold-driven — a quiet week
still produces a morning text, which is the point. "Today" is the date in
``APP_TIMEZONE`` (see ``app/localtime.py``), not UTC's date, and "yesterday"
is the local day before it.

There is a second, manual trigger: ``send_digest_now`` builds the identical
message on demand (the dashboard's "Text me this" button). It deliberately
neither reads nor writes ``DailyDigest``, so a press always sends and never
interacts with the scheduled digest in either direction.

Only ``credit``-type accounts are listed (see ``_is_card``); checking, savings,
investment and loan accounts are deliberately left out, and there is no
net-worth figure. Every count and total comes from the one spend definition
(``spending.is_spend``) over one transaction fetch.

Feature gating (soft-disable): the notifier is a clean no-op unless all four of
``TWILIO_ACCOUNT_SID`` / ``TWILIO_AUTH_TOKEN`` / ``TWILIO_FROM_NUMBER`` /
``BUDGET_ALERT_RECIPIENTS`` are set. Missing config never raises — the app can
ship inert and be verified against real spend before any number is wired up.
(``BUDGET_ALERT_RECIPIENTS`` keeps its unit-012 name on purpose: the secret
lives in the shared Doppler project, where renaming is cross-repo churn.)

Concurrency: dispatch now happens only from the single 7am job (``max_instances=1``),
not from the button-triggered sync, so overlap is not expected. The body still runs
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
from decimal import Decimal
from typing import NamedTuple, Optional

from flask import current_app
from sqlalchemy.exc import IntegrityError

from app.models import Account, DailyDigest, Institution, Transaction
from app.spending import (
    LARGE_PURCHASE, WEEKLY_BUDGET, day_spend, recent_week_spend, week_label,
    week_spend, week_start,
)

# The registered A2P 10DLC brand, carried as the first line of every message.
# Campaign registration requires the business name to appear in the body, and
# carrier traffic must match the sample messages filed with the campaign — so
# changing either constant below means re-filing those samples. See
# docs/twilio-a2p-campaign-resubmission.md.
#
# Use the legal business name exactly, not `Onerlaw`. Two registration attempts
# were rejected over names that did not match the brand on file, so brand name,
# campaign title and this constant are deliberately the same string.
BRAND = 'Onerlaw LLC'
OPT_OUT_LINE = 'Reply STOP to unsubscribe.'

# How many COMPLETED weeks of spend history ride along behind the budget line.
# Four is the smallest window that reads as a trend rather than as a comparison
# against one prior week.
HISTORY_WEEKS = 4

# The one account type the digest lists. Plaid reports a card's
# `current_balance` as the amount owed, a positive number.
CARD_TYPE = 'credit'

# Caps that keep the Yesterday section — the only part of the message whose
# length depends on the day's activity — bounded well inside Twilio's
# 1600-character body limit, where an over-long message is rejected outright
# and the day's digest is lost.
LARGE_LIST_MAX = 10
CATEGORY_LIST_MAX = 6
LABEL_MAX = 32


class AccountRow(NamedTuple):
    """One linked account, as `_account_rows` fetches it.

    Plain data, not an ORM row, so everything downstream of the query stays
    pure and unit-testable. `status` is the *institution's* status, not the
    account's — an Item that stopped syncing freezes every balance under it.
    """
    institution: str
    account: str
    mask: Optional[str]
    balance: Optional[Decimal]
    status: str
    type: Optional[str]


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
    """``Citi · Double Cash ••1234: $612.40`` (balance ``—`` when unknown).

    The balance is printed exactly as the dashboard prints it — raw
    ``current_balance``, no sign flipping — so a card's number never reads one
    way in the app and another way in the text.

    ``stale`` flags an institution that is no longer syncing (it needs a Plaid
    reconnect); its balance is frozen at the last successful sync, and a text
    has none of the dashboard's surrounding context to say so.
    """
    label = f'{institution_name} · {account_name}'
    if mask:
        label += f' ••{mask}'
    amount = '—' if balance is None else f'${balance:,.2f}'
    suffix = ' (reconnect needed)' if stale else ''
    return f'{label}: {amount}{suffix}'


def card_total_line(total):
    """``Total card debt: $1,816.73`` — the one number the card block adds up to.

    Dollars and cents, matching the balance lines it closes. Formats a negative
    total (an overpaid card) as ``-$12.34`` rather than ``$-12.34``.
    """
    sign = '-' if total < 0 else ''
    return f'Total card debt: {sign}${abs(total):,.2f}'


def history_line(ws, total):
    """``Jul 5–11: $842`` — one completed week of the trailing history.

    Whole dollars, like ``budget_line`` and unlike the balance lines: a weekly
    total is a magnitude to compare at a glance, and cents on four extra rows
    are noise. ``week_label`` is the dashboard tracker's labeller, so a week is
    named identically in the text and in the app.
    """
    return f'{week_label(ws)}: ${total:,.0f}'


def _is_card(row):
    """Is this account a credit card? The digest lists nothing else.

    Lowercased before the check — Plaid sends lowercase, but the column is a
    free-form `String(50)`. A null type (a freshly linked row) is not a card.
    """
    return (row.type or '').lower() == CARD_TYPE


def digest_cards(rows):
    """``(display_tuples, card_total)`` — pure.

    Keeps only the credit cards, as tuples ``digest_body`` unpacks straight
    into ``account_line``, and sums their balances **as printed**: raw
    ``current_balance``, no sign flip, so the total is literally the column
    above it added up. A null balance contributes nothing — its line still
    prints ``—``, so the gap is visible. A stale card is listed and counted;
    its line says it is stale.
    """
    display = []
    total = Decimal('0')
    for row in rows:
        if not _is_card(row):
            continue
        display.append((row.institution, row.account, row.mask, row.balance,
                        row.status != 'active'))
        if row.balance is not None:
            total += row.balance
    return display, total


def category_name(category):
    """``FOOD_AND_DRINK`` → ``Food and drink``; ``None`` → ``Uncategorized``."""
    if not category:
        return 'Uncategorized'
    return category.replace('_', ' ').lower().capitalize()


def _truncate(label, limit=LABEL_MAX):
    return label if len(label) <= limit else label[:limit - 1] + '…'


def yesterday_lines(day, spend):
    """The ``Yesterday`` section for ``day``, from a ``spending.DaySpend``.

    Individual purchases print dollars and cents — each is a specific amount,
    like a balance. The day's total and the category totals print whole
    dollars, like the budget and history lines, because they are magnitudes to
    compare. Both lists are capped (``LARGE_LIST_MAX``, ``CATEGORY_LIST_MAX``)
    so a busy day cannot push the message past Twilio's length limit; what the
    cap hides is still counted, as ``+N more`` or an ``Other`` line.
    """
    lines = [f"Yesterday — {day.strftime('%a %b %-d')}"]
    if not spend.count:
        lines.append('No purchases.')
        return lines
    noun = 'purchase' if spend.count == 1 else 'purchases'
    lines.append(f'{spend.count} {noun}: ${spend.total:,.0f}')

    if spend.large:
        lines.append(f'Over ${LARGE_PURCHASE:,.0f}')
        shown = spend.large[:LARGE_LIST_MAX]
        lines.extend(f'{_truncate(label)}: ${amount:,.2f}'
                     for label, amount in shown)
        if len(spend.large) > len(shown):
            lines.append(f'+{len(spend.large) - len(shown)} more')
    else:
        lines.append(f'Over ${LARGE_PURCHASE:,.0f}: none')

    lines.append('By category')
    categories = spend.by_category
    if len(categories) > CATEGORY_LIST_MAX:
        rest = sum((total for _, total in categories[CATEGORY_LIST_MAX - 1:]),
                   Decimal('0'))
        shown = [(category_name(c), t)
                 for c, t in categories[:CATEGORY_LIST_MAX - 1]]
        shown.append(('Other', rest))
    else:
        shown = [(category_name(c), t) for c, t in categories]
    lines.extend(f'{name}: ${total:,.0f}' for name, total in shown)
    return lines


def digest_body(today, spent, history, cards, card_total, yesterday,
                budget=WEEKLY_BUDGET):
    """The full SMS text.

    ``history`` is ``[(week_start, total)]`` for the completed weeks behind
    this one, oldest first (see ``spending.recent_week_spend``). ``cards`` is
    an iterable of ``(institution_name, account_name, mask, balance[, stale])``
    tuples and ``card_total`` the debt they add up to (see ``digest_cards``).
    ``yesterday`` is the ``spending.DaySpend`` for the day before ``today``.

    Every content argument is required rather than defaulted: a default would
    turn a caller that forgot one into a silently short — or silently wrong —
    digest instead of a ``TypeError``.

    The total line closes the card block, and is omitted entirely when there
    are no cards, where ``Total card debt: $0.00`` under "No linked credit
    cards." would be noise rather than information.

    Opens with ``BRAND`` and closes with ``OPT_OUT_LINE`` because A2P 10DLC
    registration requires both in the body; they are part of the message
    contract, not decoration. Both are plain GSM-7; the body itself is UCS-2
    because of ``—``/``·``/``••``.
    """
    lines = [
        BRAND,
        f"Good morning — {today.strftime('%a %b %-d')}",
        '',
        budget_line(spent, budget),
        f"Week of {week_start(today).strftime('%b %-d')}",
        '',
        f'Last {len(history)} weeks',
    ]
    lines.extend(history_line(ws, total) for ws, total in history)
    lines.extend(['', 'Credit cards'])
    card_lines = [account_line(*c) for c in cards]
    lines.extend(card_lines or ['No linked credit cards.'])
    if card_lines:
        lines.append(card_total_line(card_total))
    lines.append('')
    lines.extend(yesterday_lines(today - timedelta(days=1), yesterday))
    lines.extend(['', OPT_OUT_LINE])
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


def _has_credentials(config):
    """True when all three Twilio credentials are present."""
    return bool(config.get('TWILIO_ACCOUNT_SID')
                and config.get('TWILIO_AUTH_TOKEN')
                and config.get('TWILIO_FROM_NUMBER'))


def is_configured(config):
    """True when a digest could actually be sent right now.

    The single source of truth for the soft-disable gate — recipients that
    actually parse, AND complete credentials. The dashboard asks this to decide
    whether to render its button enabled, so it must agree exactly with what
    the send paths do; a caller re-deriving it (say, a bare truthiness check on
    the raw recipients string) would enable the button for a value like ``","``
    that parses to no recipients at all.

    Constructs nothing, so the lazy ``twilio`` import stays lazy on a page load.
    """
    return bool(_recipients(config)) and _has_credentials(config)


def _sender_from_config(config):
    """Build a TwilioSender when fully configured, else None (feature disabled)."""
    if not _has_credentials(config):
        return None
    return TwilioSender(config['TWILIO_ACCOUNT_SID'], config['TWILIO_AUTH_TOKEN'],
                        config['TWILIO_FROM_NUMBER'])


def _spend_totals(session, today, weeks=HISTORY_WEEKS):
    """``(this week's spend, [(week_start, total)], yesterday's DaySpend)``.

    One query spanning the whole window, not one per aggregate: every
    aggregate re-filters what it is handed, so a single wide fetch cannot
    inflate any of them. Yesterday is always inside the window — at earliest
    it is the Saturday before this week's Sunday, and the window reaches back
    ``weeks`` whole weeks before that. No institution filter — same household
    math as the dashboard.
    """
    current = week_start(today)
    first = current - timedelta(days=7 * weeks)
    txns = (
        session.query(Transaction)
        .filter(Transaction.removed.is_(False))
        .filter(Transaction.date >= first,
                Transaction.date < current + timedelta(days=7))
        .all()
    )
    return (week_spend(txns, today), recent_week_spend(txns, today, weeks),
            day_spend(txns, today - timedelta(days=1)))


def _account_rows(session):
    """One ``AccountRow`` per linked account — the digest's whole account fetch.

    Ordered by institution then account name, matching the dashboard's account
    cards. Every type is fetched and ``digest_cards`` keeps the cards, so the
    one predicate deciding what counts as a card lives in pure, tested code.
    Accounts with a null balance are still listed, so a freshly linked card
    shows up in the digest immediately.
    """
    rows = (
        session.query(
            Institution.name, Account.name, Account.mask,
            Account.current_balance, Institution.status, Account.type,
        )
        .select_from(Account)
        .join(Institution, Institution.id == Account.institution_id)
        .order_by(Institution.name, Account.name)
        .all()
    )
    return [AccountRow(*row) for row in rows]


def _digest_parts(session, today):
    """Everything ``digest_body`` needs, as its positional arguments.

    The impure seam between the two send paths and the pure builders — both
    call it, so neither can drift from the other in what the message contains.
    """
    spent, history, yesterday = _spend_totals(session, today)
    cards, card_total = digest_cards(_account_rows(session))
    return today, spent, history, cards, card_total, yesterday


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

        body = digest_body(*_digest_parts(session, today))

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
        body = digest_body(*_digest_parts(session, today))
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
