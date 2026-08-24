"""Daily digest SMS — budget status, recent weeks, every balance, net worth.

Once a day, right after the 7am sync (``app.sync.run_daily_sync``), every
configured recipient is texted one message: where the current Sun–Sat week's
household spend stands against ``WEEKLY_BUDGET``, what each of the four
completed weeks behind it totalled, the current balance of every linked
account, and the net worth those balances add up to. The message building is
pure and unit-tested (``digest_body`` and friends); the Twilio send and the
``DailyDigest`` writes are the impure shell.

Cadence: exactly one text per recipient per calendar day, deduped on
``(sent_date, recipient)``. Nothing here is threshold-driven — a quiet week
still produces a morning text, which is the point. "Today" is the date in
``APP_TIMEZONE`` (see ``app/localtime.py``), not UTC's date.

There is a second, manual trigger: ``send_digest_now`` builds the identical
message on demand (the dashboard's "Text me this" button). It deliberately
neither reads nor writes ``DailyDigest``, so a press always sends and never
interacts with the scheduled digest in either direction.

Net worth is assets minus liabilities over every account except those named by
``NET_WORTH_EXCLUDED_ACCOUNTS`` (see ``digest_accounts`` and
``account_net_worth``). An excluded account keeps its balance line, marked
``(not counted)`` — the total is a summary of the block above it, so a line it
does not include has to say so. Unset means nothing is excluded.

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
    WEEKLY_BUDGET, recent_week_spend, week_label, week_spend, week_start,
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

# Account types whose `current_balance` is money OWED, not money held. Plaid
# reports both as positive figures, and nothing in this app ever flips a sign
# (see `account_line`), so net worth is the one place that has to know the
# difference. Every other type — including a null one on a freshly linked row —
# is treated as an asset.
LIABILITY_TYPES = frozenset({'credit', 'loan'})


class AccountRow(NamedTuple):
    """One linked account, as `_account_rows` fetches it.

    Plain data, not an ORM row, so everything downstream of the query stays
    pure and unit-testable. `status` is the *institution's* status, not the
    account's — an Item that stopped syncing freezes every balance under it.
    """
    institution: str
    slug: str
    account: str
    mask: Optional[str]
    balance: Optional[Decimal]
    status: str
    type: Optional[str]
    unvested: Optional[Decimal]


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


def account_line(institution_name, account_name, mask, balance, stale=False,
                 excluded=False, unvested_discounted=False):
    """``Truist · Checking ••3390: $4,880.02`` (balance ``—`` when unknown).

    The balance is printed exactly as the dashboard prints it — raw
    ``current_balance``, no sign flipping — so a card's number never reads one
    way in the app and another way in the text.

    Three optional notes ride in a single parenthesical, and all of them exist
    for the same reason: a number in this list that does not mean what it
    appears to mean has to say so, because a text has none of the dashboard's
    surrounding context.

    ``stale`` flags an institution that is no longer syncing (it needs a Plaid
    reconnect); its balance is frozen at the last successful sync.
    ``excluded`` marks an account that ``NET_WORTH_EXCLUDED_ACCOUNTS`` keeps out
    of the total — it stays listed on purpose, so that an over-broad exclusion
    pattern is visible in the morning text rather than silently swallowing an
    account. ``unvested_discounted`` marks an account whose printed balance is
    knowingly larger than what it contributes, because unvested equity comp was
    netted out of the total (see ``account_net_worth``).

    ``excluded`` suppresses ``unvested_discounted``: an account contributing
    nothing at all does not also need to explain how much of it was discounted.
    """
    label = f'{institution_name} · {account_name}'
    if mask:
        label += f' ••{mask}'
    amount = '—' if balance is None else f'${balance:,.2f}'
    notes = []
    if stale:
        notes.append('reconnect needed')
    if excluded:
        notes.append('not counted')
    elif unvested_discounted:
        notes.append('unvested excluded')
    suffix = f" ({', '.join(notes)})" if notes else ''
    return f'{label}: {amount}{suffix}'


def net_worth_line(total):
    """``Net worth: $4,267.62`` — the one number the Balances block adds up to.

    Dollars and cents, matching the balance lines it closes rather than the
    whole-dollar budget and history lines: this is a balance, and it is read
    against the column directly above it.

    Formats a negative total as ``-$1,234.56`` rather than ``$-1,234.56``.
    Owing more than you hold is an entirely reachable state here — a mortgage
    is a ``loan``-type account — and the minus sign belongs in front.
    """
    sign = '-' if total < 0 else ''
    return f'Net worth: {sign}${abs(total):,.2f}'


def history_line(ws, total):
    """``Jul 5–11: $842`` — one completed week of the trailing history.

    Whole dollars, like ``budget_line`` and unlike the balance lines: a weekly
    total is a magnitude to compare at a glance, and cents on four extra rows
    are noise. ``week_label`` is the dashboard tracker's labeller, so a week is
    named identically in the text and in the app.
    """
    return f'{week_label(ws)}: ${total:,.0f}'


def _excluded_patterns(config):
    """Parse ``NET_WORTH_EXCLUDED_ACCOUNTS`` — split, strip, drop empty.

    Same shape as ``_recipients`` and ``CHAT_MODELS``, for the same reason: a
    comma-separated env var is what Doppler holds, and a value like ``","``
    must parse to nothing rather than to one blank pattern that matches
    everything.
    """
    raw = config.get('NET_WORTH_EXCLUDED_ACCOUNTS') or ''
    return [p.strip() for p in raw.split(',') if p.strip()]


def _pattern_matches(pattern, row):
    """Does ``institution:account`` name this account? Case-insensitive.

    The institution half must appear in ``Institution.slug`` or
    ``Institution.name`` (substring, so ``sofi`` finds ``SoFi``). The account
    half must equal the ``mask`` exactly or appear in ``Account.name``.

    **Both halves must match.** A bare ``checking`` cannot be written, and a
    pattern is therefore anchored to one institution — otherwise excluding "the
    SoFi checking account" would silently take the Truist one with it. A
    pattern with no colon (or an empty account half) deliberately matches every
    account at that institution, which is how a whole bank is dropped.

    Substring rather than equality on the institution because the display name
    Plaid hands back is not something the user types from memory; equality on
    the mask because a four-digit substring match across accounts is a coin
    flip.
    """
    inst_part, _, acct_part = pattern.partition(':')
    inst_part = inst_part.strip().lower()
    acct_part = acct_part.strip().lower()
    if not inst_part:
        return False
    if (inst_part not in (row.institution or '').lower()
            and inst_part not in (row.slug or '').lower()):
        return False
    if not acct_part:
        return True
    return (acct_part == (row.mask or '').lower()
            or acct_part in (row.account or '').lower())


def _is_liability(row):
    """Is this account's balance money owed rather than money held?

    The single predicate behind both the sign `account_net_worth` applies and
    the note `digest_accounts` attaches to the line. Deriving them separately
    is how a line comes to claim a discount the total never applied: nothing in
    the schema stops a `credit` row from also carrying an `unvested_value`.

    Lowercased before the check — Plaid sends lowercase, but the column is a
    free-form `String(50)`.
    """
    return (row.type or '').lower() in LIABILITY_TYPES


def account_net_worth(row):
    """What one account contributes to the total. Signed.

    - A liability (``LIABILITY_TYPES``) contributes its balance **negated**:
      Plaid reports a card's or loan's ``current_balance`` as the amount owed,
      a positive number, and nothing upstream flips it.
    - An asset contributes its balance **less any unvested equity comp**.
      Subtracting ``unvested_value`` is deliberately not the same as
      substituting ``vested_value``: that column sums only the holdings which
      report a known vested figure, so a plain brokerage position in the same
      account appears in neither equity total, and substituting would drop its
      value entirely. ``balance - unvested`` keeps ordinary holdings whole and
      discounts only the part that is not yours yet.
    - The result is clamped at zero for an asset, mirroring how
      ``sync._refresh_investments`` clamps the unvested remainder itself: the
      two figures come from different Plaid endpoints, so a stale holdings
      price can price the unvested portion above the account's own balance, and
      a negative asset is never the right answer.
    - A null balance contributes nothing. The account still prints its ``—``
      line, so the gap is visible rather than silently zeroed.
    """
    if row.balance is None:
        return Decimal('0')
    if _is_liability(row):
        return -row.balance
    if row.unvested is None:
        return row.balance
    return max(row.balance - row.unvested, Decimal('0'))


def digest_accounts(rows, patterns):
    """``(display_tuples, net_worth_total, unmatched_patterns)`` — pure.

    One pass over the fetched rows produces everything the message needs: the
    tuples ``digest_body`` unpacks straight into ``account_line``, the signed
    total of every account no pattern excluded, and the patterns that named no
    account at all.

    Unmatched patterns are **returned, not logged**. A typo'd or stale
    exclusion is exactly the failure this feature must not have — it silently
    counts an account the user believes is excluded — but logging is a side
    effect, and keeping it out here is what lets the whole derivation be tested
    without an app context. The impure caller logs what it is handed.

    An excluded account stays in ``display_tuples``. The complementary failure
    — a pattern matching more than intended — has no counter of its own; it is
    caught by the ``(not counted)`` suffix showing up on a line the user did
    not expect.
    """
    matched = set()
    display = []
    total = Decimal('0')
    for row in rows:
        hits = [p for p in patterns if _pattern_matches(p, row)]
        matched.update(hits)
        excluded = bool(hits)
        discounted = (row.unvested is not None and row.unvested > 0
                      and not _is_liability(row))
        display.append((
            row.institution, row.account, row.mask, row.balance,
            row.status != 'active', excluded, discounted,
        ))
        if not excluded:
            total += account_net_worth(row)
    unmatched = [p for p in patterns if p not in matched]
    return display, total, unmatched


def digest_body(today, spent, accounts, history, net_worth, budget=WEEKLY_BUDGET):
    """The full SMS text.

    ``accounts`` is an iterable of ``(institution_name, account_name, mask,
    balance[, stale[, excluded[, unvested_discounted]]])`` tuples — plain data,
    not ORM rows, so this stays pure. ``history`` is ``[(week_start, total)]``
    for the completed weeks behind this one, oldest first (see
    ``spending.recent_week_spend``). ``net_worth`` is the signed total those
    accounts add up to (see ``digest_accounts``); it is passed in rather than
    derived here because deriving it needs the account *types*, which the
    display tuples deliberately do not carry.

    ``history`` and ``net_worth`` are both required rather than defaulted: a
    default would turn a caller that forgot one into a silently short — or
    silently wrong — digest instead of a ``TypeError``.

    The net-worth line closes the Balances block, and is omitted entirely when
    there are no accounts, where ``Net worth: $0.00`` under "No linked
    accounts." would be noise rather than information.

    Opens with ``BRAND`` and closes with ``OPT_OUT_LINE`` because A2P 10DLC
    registration requires both in the body; they are part of the message
    contract, not decoration. Both are plain GSM-7, so they add roughly one
    UCS-2 segment to a body already pushed off GSM-7 by ``—``/``·``/``••``.
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
    lines.extend(['', 'Balances'])
    account_lines = [account_line(*a) for a in accounts]
    lines.extend(account_lines or ['No linked accounts.'])
    if account_lines:
        lines.extend(['', net_worth_line(net_worth)])
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


def _week_totals(session, today, weeks=HISTORY_WEEKS):
    """This week's spend, plus ``[(week_start, total)]`` for the ``weeks`` before it.

    One query spanning the whole window, not one per week: both aggregates
    re-filter what they are handed, so a single wide fetch cannot inflate
    either. No institution filter — same household math as the dashboard.
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
    return week_spend(txns, today), recent_week_spend(txns, today, weeks)


def _account_rows(session):
    """One ``AccountRow`` per linked account — the digest's whole account fetch.

    Ordered by institution then account name, matching the dashboard's account
    cards. Accounts with a null balance are still listed, so a freshly linked
    account shows up in the digest immediately.

    Carries more than the message prints: ``slug`` and ``mask`` are what an
    exclusion pattern matches against, ``type`` is what decides an asset from a
    liability, and ``unvested`` is what comes back out of an equity-comp
    balance. All of it is read once here, so ``digest_accounts`` can derive the
    lines and the total together without a second query.
    """
    rows = (
        session.query(
            Institution.name, Institution.slug, Account.name, Account.mask,
            Account.current_balance, Institution.status, Account.type,
            Account.unvested_value,
        )
        .select_from(Account)
        .join(Institution, Institution.id == Account.institution_id)
        .order_by(Institution.name, Account.name)
        .all()
    )
    return [AccountRow(*row) for row in rows]


def _digest_parts(session, config, today):
    """Everything ``digest_body`` needs, plus the warning the caller must emit.

    The impure seam between the two send paths and the pure builders — both
    call it, so neither can drift from the other in what the message contains.
    Returns ``(body_args, unmatched_patterns)``.
    """
    spent, history = _week_totals(session, today)
    accounts, net_worth, unmatched = digest_accounts(
        _account_rows(session), _excluded_patterns(config),
    )
    return (today, spent, accounts, history, net_worth), unmatched


def _warn_unmatched(unmatched):
    """Log exclusion patterns that named no account.

    Silent no-match is the one failure mode this feature cannot afford: the
    user believes an account is excluded, the total says otherwise, and nothing
    anywhere says why. A renamed account or a typo'd pattern both land here.
    """
    if unmatched:
        current_app.logger.warning(
            'NET_WORTH_EXCLUDED_ACCOUNTS matched no account: %s',
            ', '.join(unmatched),
        )


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

        body_args, unmatched = _digest_parts(session, config, today)
        _warn_unmatched(unmatched)
        body = digest_body(*body_args)

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
        body_args, unmatched = _digest_parts(session, config, today)
        _warn_unmatched(unmatched)
        body = digest_body(*body_args)
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
