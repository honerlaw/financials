import threading
from datetime import date

import pytest
from decimal import Decimal

from sqlalchemy.exc import OperationalError

from app.models import db, Account, Institution, Transaction, DailyDigest
from app.notifications import (
    account_line, budget_line, digest_body, send_daily_digest, send_digest_now,
)


# 2026-08-08 is a Saturday; its Sun–Sat week starts Aug 2 (a Sunday).
TODAY = date(2026, 8, 8)
WS = date(2026, 8, 2)


# ── message building (pure) ───────────────────────────────────────────────────

def test_budget_line_under_budget():
    line = budget_line(Decimal('750'))
    assert line == 'Budget: $750 of $1,000 (75%) — $250 left'


def test_budget_line_at_budget_reads_zero_left():
    assert budget_line(Decimal('1000')) == 'Budget: $1,000 of $1,000 (100%) — $0 left'


def test_budget_line_over_budget_reports_percent_and_overage():
    """Percent keeps climbing past 100 and the tail flips to OVER."""
    line = budget_line(Decimal('1240'))
    assert '(124%)' in line
    assert '$240 OVER' in line


def test_budget_line_zero_spend():
    assert budget_line(Decimal('0')) == 'Budget: $0 of $1,000 (0%) — $1,000 left'


def test_account_line_formats_label_and_balance():
    assert account_line('Truist', 'Checking', '3390', Decimal('4880.02')) == \
        'Truist · Checking ••3390: $4,880.02'


def test_account_line_without_mask():
    assert account_line('Amex', 'Platinum', None, Decimal('12.00')) == \
        'Amex · Platinum: $12.00'


def test_account_line_null_balance_renders_dash():
    assert account_line('Citi', 'New Card', '8821', None) == 'Citi · New Card ••8821: —'


def test_account_line_flags_a_bank_that_stopped_syncing():
    """A non-active institution is skipped by the sync, so its balance is frozen —
    the text must say so rather than present a stale number as current."""
    assert account_line('Citi', 'Card', '8821', Decimal('10'), stale=True) == \
        'Citi · Card ••8821: $10.00 (reconnect needed)'


def test_digest_body_contains_budget_week_and_every_account():
    body = digest_body(TODAY, Decimal('750'), [
        ('Amex', 'Platinum', '1004', Decimal('2143.19')),
        ('Truist', 'Checking', '3390', Decimal('4880.02')),
    ])
    assert body.startswith('Good morning — Sat Aug 8')
    assert 'Budget: $750 of $1,000 (75%) — $250 left' in body
    assert 'Week of Aug 2' in body
    assert 'Amex · Platinum ••1004: $2,143.19' in body
    assert 'Truist · Checking ••3390: $4,880.02' in body


def test_digest_body_with_no_accounts():
    body = digest_body(TODAY, Decimal('0'), [])
    assert 'No linked accounts.' in body


# ── send_daily_digest (orchestration) ─────────────────────────────────────────

class FakeSender:
    """Records sends; optionally raises for specific recipients."""

    def __init__(self, fail_for=()):
        self.sent = []
        self.fail_for = set(fail_for)

    def send(self, to, body):
        if to in self.fail_for:
            raise RuntimeError('twilio down')
        self.sent.append((to, body))


def _seed_inst(week_total=None, txn_date=None, name='B', accounts=(),
               status='active'):
    """Insert an institution, optionally one current-week txn and some accounts."""
    inst = Institution(name=name, slug=name.lower(), access_token='a',
                       item_id=f'i-{name}', status=status)
    db.session.add(inst)
    db.session.commit()
    if week_total is not None:
        db.session.add(Transaction(
            plaid_transaction_id=f't1-{name}', institution_id=inst.id,
            account_id='a1', date=txn_date or TODAY, description='x',
            amount=Decimal(week_total), category='FOOD_AND_DRINK',
        ))
    for i, (acct_name, mask, balance) in enumerate(accounts):
        db.session.add(Account(
            institution_id=inst.id, plaid_account_id=f'{name}-acct-{i}',
            name=acct_name, mask=mask, current_balance=balance,
        ))
    db.session.commit()
    return inst.id


def test_sends_one_digest_to_each_recipient(app):
    with app.app_context():
        _seed_inst('750.00', accounts=[('Checking', '3390', Decimal('4880.02'))])
        cfg = {'BUDGET_ALERT_RECIPIENTS': '+1111,+1222'}
        sender = FakeSender()
        send_daily_digest(db.session, TODAY, cfg, sender=sender)

        assert len(sender.sent) == 2
        assert {to for to, _ in sender.sent} == {'+1111', '+1222'}
        assert DailyDigest.query.count() == 2
        assert {r.sent_date for r in DailyDigest.query.all()} == {TODAY}
        # Both budget status and balances ride in the one message.
        body = sender.sent[0][1]
        assert '75%' in body and '$750' in body
        assert 'B · Checking ••3390: $4,880.02' in body


def test_digest_lists_every_account_ordered_by_institution(app):
    with app.app_context():
        _seed_inst('0.00', name='Zeta', accounts=[('Savings', '1111', Decimal('10'))])
        _seed_inst(None, name='Alpha', accounts=[
            ('Checking', '2222', Decimal('20')),
            ('Brokerage', '3333', None),  # null balance still listed
        ])
        sender = FakeSender()
        send_daily_digest(db.session, TODAY,
                          {'BUDGET_ALERT_RECIPIENTS': '+1111'}, sender=sender)

        body = sender.sent[0][1]
        assert 'Alpha · Brokerage ••3333: —' in body
        assert body.index('Alpha · Brokerage') < body.index('Alpha · Checking') \
            < body.index('Zeta · Savings')


def test_digest_flags_accounts_of_a_bank_needing_reconnect(app):
    """sync_all_institutions only syncs status='active', so a login_required
    bank's balance is frozen at its last good sync — the digest must not present
    it as current."""
    with app.app_context():
        _seed_inst('0.00', name='Stale', status='login_required',
                   accounts=[('Card', '9999', Decimal('42'))])
        _seed_inst(None, name='Fresh', accounts=[('Checking', '1111', Decimal('7'))])
        sender = FakeSender()
        send_daily_digest(db.session, TODAY,
                          {'BUDGET_ALERT_RECIPIENTS': '+1111'}, sender=sender)

        body = sender.sent[0][1]
        assert 'Stale · Card ••9999: $42.00 (reconnect needed)' in body
        assert 'Fresh · Checking ••1111: $7.00' in body
        assert 'Fresh · Checking ••1111: $7.00 (reconnect' not in body


def test_over_budget_digest_reports_overage(app):
    with app.app_context():
        _seed_inst('1240.00')
        sender = FakeSender()
        send_daily_digest(db.session, TODAY,
                          {'BUDGET_ALERT_RECIPIENTS': '+1111'}, sender=sender)
        assert '$240 OVER' in sender.sent[0][1]


def test_second_run_same_day_sends_nothing(app):
    with app.app_context():
        _seed_inst('600.00')
        cfg = {'BUDGET_ALERT_RECIPIENTS': '+1111'}
        first = FakeSender()
        send_daily_digest(db.session, TODAY, cfg, sender=first)
        assert len(first.sent) == 1

        second = FakeSender()
        send_daily_digest(db.session, TODAY, cfg, sender=second)
        assert second.sent == []
        assert DailyDigest.query.filter_by(recipient='+1111').count() == 1


def test_next_day_sends_again(app):
    with app.app_context():
        _seed_inst('600.00')
        cfg = {'BUDGET_ALERT_RECIPIENTS': '+1111'}
        send_daily_digest(db.session, TODAY, cfg, sender=FakeSender())
        tomorrow = FakeSender()
        send_daily_digest(db.session, date(2026, 8, 9), cfg, sender=tomorrow)
        assert len(tomorrow.sent) == 1
        assert DailyDigest.query.count() == 2


def test_only_untexted_recipients_are_sent_to(app):
    """Adding a recipient mid-day texts only the new one."""
    with app.app_context():
        _seed_inst('600.00')
        send_daily_digest(db.session, TODAY,
                          {'BUDGET_ALERT_RECIPIENTS': '+1111'}, sender=FakeSender())
        sender = FakeSender()
        send_daily_digest(db.session, TODAY,
                          {'BUDGET_ALERT_RECIPIENTS': '+1111,+1222'}, sender=sender)
        assert [to for to, _ in sender.sent] == ['+1222']


def test_noop_when_no_recipients(app):
    with app.app_context():
        _seed_inst('900.00')
        sender = FakeSender()
        send_daily_digest(db.session, TODAY, {'BUDGET_ALERT_RECIPIENTS': ''},
                          sender=sender)
        assert sender.sent == []
        assert DailyDigest.query.count() == 0


def test_noop_when_credentials_missing_and_no_injected_sender(app):
    with app.app_context():
        _seed_inst('900.00')
        # Recipients set, but no TWILIO_* creds and no injected sender → disabled.
        send_daily_digest(db.session, TODAY, {'BUDGET_ALERT_RECIPIENTS': '+1111'})
        assert DailyDigest.query.count() == 0


def test_noop_when_partial_credentials(app):
    """Partial Twilio config (some creds blank) soft-disables — no send, no row."""
    with app.app_context():
        _seed_inst('900.00')
        cfg = {
            'BUDGET_ALERT_RECIPIENTS': '+1111',
            'TWILIO_ACCOUNT_SID': 'sid', 'TWILIO_AUTH_TOKEN': 'tok',
            'TWILIO_FROM_NUMBER': '',  # missing → feature disabled
        }
        # sender=None forces the config path; must build no TwilioSender.
        send_daily_digest(db.session, TODAY, cfg)
        assert DailyDigest.query.count() == 0


def test_failed_send_is_not_recorded_and_retries(app):
    with app.app_context():
        _seed_inst('600.00')
        cfg = {'BUDGET_ALERT_RECIPIENTS': '+1111'}
        failing = FakeSender(fail_for={'+1111'})
        # Must not raise even though the send fails.
        send_daily_digest(db.session, TODAY, cfg, sender=failing)
        assert DailyDigest.query.count() == 0  # unrecorded → retryable

        working = FakeSender()
        send_daily_digest(db.session, TODAY, cfg, sender=working)
        assert len(working.sent) == 1
        assert DailyDigest.query.count() == 1


def test_one_recipient_failure_does_not_block_the_other(app):
    with app.app_context():
        _seed_inst('600.00')
        sender = FakeSender(fail_for={'+1111'})
        send_daily_digest(db.session, TODAY,
                          {'BUDGET_ALERT_RECIPIENTS': '+1111,+1222'}, sender=sender)
        assert [to for to, _ in sender.sent] == ['+1222']
        assert [r.recipient for r in DailyDigest.query.all()] == ['+1222']


class _FlakyCommitSession:
    """Delegates to a real session but raises a non-Integrity error on commit."""

    def __init__(self, real, fail_times=1):
        self._real = real
        self._fail = fail_times

    def query(self, *a, **k):
        return self._real.query(*a, **k)

    def add(self, *a, **k):
        return self._real.add(*a, **k)

    def rollback(self, *a, **k):
        return self._real.rollback(*a, **k)

    def commit(self):
        if self._fail > 0:
            self._fail -= 1
            raise OperationalError('stmt', {}, Exception('db down'))
        return self._real.commit()


def test_commit_failure_after_send_is_swallowed_and_not_recorded(app):
    """A non-Integrity commit failure after a successful send must not propagate,
    must roll back, and must leave no dedup row (so it is retried, not lost)."""
    with app.app_context():
        _seed_inst('600.00')
        cfg = {'BUDGET_ALERT_RECIPIENTS': '+1111'}
        sender = FakeSender()
        flaky = _FlakyCommitSession(db.session, fail_times=1)
        # Must not raise despite the commit blowing up.
        send_daily_digest(flaky, TODAY, cfg, sender=sender)
        assert len(sender.sent) == 1          # the SMS did go out
        assert DailyDigest.query.count() == 0  # but nothing was recorded


def test_concurrent_calls_do_not_double_send(tmp_path):
    """Two overlapping dispatches must not double-text the day's digest.

    Uses a file-backed SQLite DB so the two threads share one database (the
    module-level lock is what must serialize them).
    """
    from app import create_app
    from app.models import db as _db

    cfg = {
        'TESTING': True,
        'SQLALCHEMY_DATABASE_URI': f"sqlite:///{tmp_path}/t.db",
        'APP_PASSWORD': 'p', 'SECRET_KEY': 's',
        'BUDGET_ALERT_RECIPIENTS': '+1111',
    }
    app = create_app(cfg)
    with app.app_context():
        _db.create_all()
        inst = Institution(name='B', slug='b', access_token='a', item_id='i')
        _db.session.add(inst)
        _db.session.commit()
        _db.session.add(Transaction(
            plaid_transaction_id='t1', institution_id=inst.id, account_id='a1',
            date=TODAY, description='x', amount=Decimal('600.00'),
            category='FOOD_AND_DRINK',
        ))
        _db.session.commit()

    sender = FakeSender()
    barrier = threading.Barrier(2)

    def worker():
        with app.app_context():
            barrier.wait()  # maximize contention on the lock
            send_daily_digest(_db.session, TODAY, cfg, sender=sender)
            _db.session.remove()

    threads = [threading.Thread(target=worker) for _ in range(2)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()

    with app.app_context():
        assert len(sender.sent) == 1
        assert DailyDigest.query.filter_by(recipient='+1111').count() == 1


# ── send_digest_now (manual trigger) ──────────────────────────────────────────

def test_manual_send_texts_every_recipient_the_same_message(app):
    with app.app_context():
        _seed_inst('750.00', accounts=[('Checking', '3390', Decimal('4880.02'))])
        sender = FakeSender()
        result = send_digest_now(db.session, TODAY,
                                 {'BUDGET_ALERT_RECIPIENTS': '+1111,+1222'},
                                 sender=sender)
        assert result == {'configured': True, 'sent': ['+1111', '+1222'], 'failed': []}
        assert len(sender.sent) == 2
        body = sender.sent[0][1]
        assert '75%' in body
        assert 'B · Checking ••3390: $4,880.02' in body
        # Identical to what the scheduled path would send for the same data.
        scheduled = FakeSender()
        send_daily_digest(db.session, TODAY,
                          {'BUDGET_ALERT_RECIPIENTS': '+1111'}, sender=scheduled)
        assert scheduled.sent[0][1] == body


def test_manual_send_writes_no_dedup_row(app):
    """A press must not claim the day — tomorrow's 7am digest is unaffected."""
    with app.app_context():
        _seed_inst('600.00')
        cfg = {'BUDGET_ALERT_RECIPIENTS': '+1111'}
        send_digest_now(db.session, TODAY, cfg, sender=FakeSender())
        assert DailyDigest.query.count() == 0


def test_manual_send_works_after_the_scheduled_digest_already_went_out(app):
    """The dedup row blocks the scheduled path, never the button."""
    with app.app_context():
        _seed_inst('600.00')
        cfg = {'BUDGET_ALERT_RECIPIENTS': '+1111'}
        send_daily_digest(db.session, TODAY, cfg, sender=FakeSender())
        assert DailyDigest.query.count() == 1

        manual = FakeSender()
        result = send_digest_now(db.session, TODAY, cfg, sender=manual)
        assert result['sent'] == ['+1111']
        assert len(manual.sent) == 1


def test_manual_send_does_not_suppress_the_scheduled_digest(app):
    """The other direction: pressing early must not cancel the morning text."""
    with app.app_context():
        _seed_inst('600.00')
        cfg = {'BUDGET_ALERT_RECIPIENTS': '+1111'}
        send_digest_now(db.session, TODAY, cfg, sender=FakeSender())

        scheduled = FakeSender()
        send_daily_digest(db.session, TODAY, cfg, sender=scheduled)
        assert len(scheduled.sent) == 1
        assert DailyDigest.query.count() == 1


def test_manual_send_is_repeatable(app):
    with app.app_context():
        _seed_inst('600.00')
        cfg = {'BUDGET_ALERT_RECIPIENTS': '+1111'}
        first = FakeSender()
        second = FakeSender()
        send_digest_now(db.session, TODAY, cfg, sender=first)
        send_digest_now(db.session, TODAY, cfg, sender=second)
        assert len(first.sent) == 1 and len(second.sent) == 1


def test_manual_send_reports_unconfigured_rather_than_silently_succeeding(app):
    with app.app_context():
        _seed_inst('600.00')
        assert send_digest_now(db.session, TODAY, {'BUDGET_ALERT_RECIPIENTS': ''}) == \
            {'configured': False, 'sent': [], 'failed': []}
        # Recipients set but no credentials and no injected sender.
        assert send_digest_now(db.session, TODAY,
                               {'BUDGET_ALERT_RECIPIENTS': '+1111'})['configured'] is False


def test_manual_send_reports_partial_failure(app):
    with app.app_context():
        _seed_inst('600.00')
        sender = FakeSender(fail_for={'+1111'})
        result = send_digest_now(db.session, TODAY,
                                 {'BUDGET_ALERT_RECIPIENTS': '+1111,+1222'},
                                 sender=sender)
        assert result['sent'] == ['+1222']
        assert result['failed'] == ['+1111']


# ── the real TwilioSender construction path ───────────────────────────────────
#
# Every other test in this file injects a fake sender, so `_sender_from_config`
# — the line that actually threw in production — was never executed by the
# suite. These stub the `twilio` package in sys.modules so the real construction
# path runs identically whether or not twilio is installed locally.

def _twilio_stub(raise_on_client=None):
    """A minimal fake `twilio` package tree for sys.modules."""
    import sys, types

    rest = types.ModuleType('twilio.rest')
    http = types.ModuleType('twilio.http')
    http_client = types.ModuleType('twilio.http.http_client')
    root = types.ModuleType('twilio')

    class _Client:
        def __init__(self, sid, token, http_client=None):
            if raise_on_client:
                raise raise_on_client
            self.sid = sid

    class _TwilioHttpClient:
        def __init__(self, timeout=None):
            self.timeout = timeout

    rest.Client = _Client
    http_client.TwilioHttpClient = _TwilioHttpClient
    return {'twilio': root, 'twilio.rest': rest, 'twilio.http': http,
            'twilio.http.http_client': http_client}


def test_sender_is_constructed_from_complete_config(app):
    """The real _sender_from_config path, not an injected fake."""
    from unittest.mock import patch as _patch
    from app.notifications import _sender_from_config

    with _patch.dict('sys.modules', _twilio_stub()):
        sender = _sender_from_config({
            'TWILIO_ACCOUNT_SID': 'AC' + '0' * 32,
            'TWILIO_AUTH_TOKEN': '0' * 32,
            'TWILIO_FROM_NUMBER': '+15550000000',
        })
    assert sender is not None
    assert sender._from == '+15550000000'


def test_sender_construction_failure_propagates(app):
    """A bad credential blows up at construction — the caller must handle it.

    This is the production failure shape: the exception escapes send_digest_now
    rather than being caught per-recipient.
    """
    from unittest.mock import patch as _patch

    with _patch.dict('sys.modules', _twilio_stub(raise_on_client=RuntimeError('bad creds'))):
        with pytest.raises(RuntimeError):
            send_digest_now(db.session, TODAY, {
                'BUDGET_ALERT_RECIPIENTS': '+1111',
                'TWILIO_ACCOUNT_SID': 'AC' + '0' * 32,
                'TWILIO_AUTH_TOKEN': '0' * 32,
                'TWILIO_FROM_NUMBER': '+15550000000',
            })
