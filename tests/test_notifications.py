import threading
from datetime import date

import pytest
from decimal import Decimal

from sqlalchemy.exc import OperationalError

from app.models import db, Account, Institution, Transaction, DailyDigest
from app.notifications import (
    AccountRow, account_line, account_net_worth, budget_line, digest_accounts,
    digest_body, history_line, net_worth_line, send_daily_digest,
    send_digest_now,
)


# 2026-08-08 is a Saturday; its Sun–Sat week starts Aug 2 (a Sunday).
TODAY = date(2026, 8, 8)
WS = date(2026, 8, 2)
# The four completed weeks behind it, oldest first — what recent_week_spend
# hands digest_body.
HISTORY = [
    (date(2026, 7, 5), Decimal('842')),
    (date(2026, 7, 12), Decimal('1130')),
    (date(2026, 7, 19), Decimal('0')),
    (date(2026, 7, 26), Decimal('1204')),
]


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
    ], HISTORY, Decimal('7023.21'))
    assert body.startswith('Onerlaw LLC\nGood morning — Sat Aug 8')
    assert 'Budget: $750 of $1,000 (75%) — $250 left' in body
    assert 'Week of Aug 2' in body
    assert 'Amex · Platinum ••1004: $2,143.19' in body
    assert 'Truist · Checking ••3390: $4,880.02' in body


def test_digest_body_with_no_accounts():
    body = digest_body(TODAY, Decimal('0'), [], HISTORY, Decimal('0'))
    assert 'No linked accounts.' in body


@pytest.mark.parametrize('accounts', [
    [],
    [('Amex', 'Platinum', '1004', Decimal('2143.19'))],
])
def test_digest_body_is_branded_and_carries_opt_out(accounts):
    """A2P 10DLC registration requires the business name and opt-out language in
    the body, and carrier traffic has to match the samples filed with the
    campaign — so this holds whether or not any account is linked."""
    body = digest_body(TODAY, Decimal('750'), accounts, HISTORY, Decimal('12'))
    assert body.startswith('Onerlaw LLC\n')
    assert body.endswith('\nReply STOP to unsubscribe.')


def test_history_line_formats_a_week_in_whole_dollars():
    assert history_line(date(2026, 7, 5), Decimal('842.47')) == 'Jul 5–11: $842'
    assert history_line(date(2026, 7, 26), Decimal('1204')) == 'Jul 26 – Aug 1: $1,204'


def test_digest_body_lists_the_four_completed_weeks_oldest_first():
    body = digest_body(TODAY, Decimal('750'), [], HISTORY, Decimal('0'))
    assert 'Last 4 weeks' in body
    for expected in ('Jul 5–11: $842', 'Jul 12–18: $1,130',
                     'Jul 19–25: $0', 'Jul 26 – Aug 1: $1,204'):
        assert expected in body
    assert body.index('Jul 5–11') < body.index('Jul 12–18') \
        < body.index('Jul 19–25') < body.index('Jul 26 – Aug 1')


def test_digest_body_puts_the_history_between_budget_and_balances():
    body = digest_body(TODAY, Decimal('750'), [
        ('Truist', 'Checking', '3390', Decimal('4880.02')),
    ], HISTORY, Decimal('4880.02'))
    assert body.index('Week of Aug 2') < body.index('Last 4 weeks') \
        < body.index('Balances')


def test_digest_body_history_never_repeats_the_current_week():
    """The running week is the budget line's job; a partial week in a column of
    finished ones reads as a drop that is not real."""
    body = digest_body(TODAY, Decimal('750'), [], HISTORY, Decimal('0'))
    assert 'Aug 2–8' not in body


# ── net worth (pure) ──────────────────────────────────────────────────────────

def _row(institution='SoFi', slug='sofi', account='Checking', mask='1234',
         balance=Decimal('100'), status='active', type='depository',
         unvested=None):
    return AccountRow(institution, slug, account, mask, balance, status, type,
                      unvested)


def test_net_worth_line_formats_dollars_and_cents():
    assert net_worth_line(Decimal('4267.62')) == 'Net worth: $4,267.62'
    assert net_worth_line(Decimal('0')) == 'Net worth: $0.00'


def test_net_worth_line_puts_the_minus_before_the_dollar_sign():
    """Owing more than you hold is reachable — a mortgage is a loan account."""
    assert net_worth_line(Decimal('-1234.56')) == 'Net worth: -$1,234.56'


def test_asset_contributes_its_balance():
    assert account_net_worth(_row(balance=Decimal('4880.02'))) == Decimal('4880.02')


@pytest.mark.parametrize('acct_type', ['credit', 'loan'])
def test_liability_balance_is_subtracted(acct_type):
    """Plaid reports a card's or loan's balance as the amount OWED, positive,
    and nothing upstream flips the sign — net worth is the only place that
    knows the difference."""
    row = _row(balance=Decimal('612.40'), type=acct_type)
    assert account_net_worth(row) == Decimal('-612.40')


def test_liability_type_matching_is_case_insensitive():
    assert account_net_worth(_row(balance=Decimal('10'), type='CREDIT')) \
        == Decimal('-10')


def test_unknown_or_null_type_counts_as_an_asset():
    for acct_type in (None, 'other', 'investment'):
        assert account_net_worth(_row(balance=Decimal('50'), type=acct_type)) \
            == Decimal('50')


def test_null_balance_contributes_nothing():
    assert account_net_worth(_row(balance=None)) == Decimal('0')


def test_unvested_equity_is_netted_out_of_an_asset():
    """`vested_value` sums only holdings reporting a vested figure, so plain
    brokerage positions in the same account appear in neither equity total —
    substituting it would drop them. Subtracting `unvested_value` keeps them."""
    row = _row(balance=Decimal('84200'), type='investment',
               unvested=Decimal('52800'))
    assert account_net_worth(row) == Decimal('31400')


def test_unvested_larger_than_the_balance_clamps_at_zero():
    """The balance and the holdings valuation come from different Plaid
    endpoints, so a stale price can put unvested above the account's balance."""
    row = _row(balance=Decimal('100'), type='investment',
               unvested=Decimal('500'))
    assert account_net_worth(row) == Decimal('0')


# ── exclusion patterns (pure) ─────────────────────────────────────────────────

@pytest.mark.parametrize('pattern', [
    'sofi:checking',      # slug + account name
    'SoFi:CHECKING',      # case-insensitive on both halves
    'sofi:1234',          # account half as an exact mask
    'so:check',           # substrings on both halves
    'sofi',               # no account half: the whole institution
    'sofi:',              # empty account half reads the same way
])
def test_patterns_that_name_the_sofi_checking_account(pattern):
    display, total, unmatched = digest_accounts([_row()], [pattern])
    assert total == Decimal('0')
    assert unmatched == []
    assert display[0][5] is True


@pytest.mark.parametrize('pattern', [
    'truist:checking',    # right account name, wrong bank
    'sofi:savings',       # right bank, wrong account
    'sofi:123',           # mask must match exactly, not by substring
    ':checking',          # an account half alone can never match
])
def test_patterns_that_do_not_name_it(pattern):
    display, total, unmatched = digest_accounts([_row()], [pattern])
    assert total == Decimal('100')
    assert unmatched == [pattern]
    assert display[0][5] is False


def test_a_pattern_is_anchored_to_one_institution():
    """Excluding "the SoFi checking account" must not take the Truist one."""
    rows = [_row(), _row(institution='Truist', slug='truist', mask='3390',
                         balance=Decimal('4880.02'))]
    display, total, _ = digest_accounts(rows, ['sofi:checking'])
    assert total == Decimal('4880.02')
    assert [d[5] for d in display] == [True, False]


def test_the_institution_display_name_also_matches():
    row = _row(institution='SoFi Bank', slug='ins_116794')
    _, total, unmatched = digest_accounts([row], ['sofi bank:checking'])
    assert total == Decimal('0') and unmatched == []


def test_unmatched_patterns_are_returned_rather_than_swallowed():
    """A typo'd or stale pattern silently counts an account the user believes
    is excluded — the caller has to be able to say so."""
    _, total, unmatched = digest_accounts([_row()], ['sofi:checking', 'chase:x'])
    assert total == Decimal('0')
    assert unmatched == ['chase:x']


def test_an_excluded_account_is_still_displayed():
    """It stays listed so an over-broad pattern shows up in the morning text."""
    display, _, _ = digest_accounts([_row()], ['sofi'])
    assert len(display) == 1
    assert display[0][:4] == ('SoFi', 'Checking', '1234', Decimal('100'))


def test_digest_accounts_totals_assets_against_liabilities():
    rows = [
        _row(institution='Truist', slug='truist', balance=Decimal('4880.02')),
        _row(institution='Citi', slug='citi', account='Double Cash',
             balance=Decimal('612.40'), type='credit'),
        _row(institution='SoFi', slug='sofi', balance=Decimal('412.00')),
    ]
    _, total, _ = digest_accounts(rows, ['sofi:checking'])
    assert total == Decimal('4267.62')


def test_a_stale_account_still_counts_toward_net_worth():
    """Its line already says (reconnect needed); dropping the balance entirely
    would understate net worth far worse than a slightly old number does."""
    display, total, _ = digest_accounts([_row(status='login_required')], [])
    assert total == Decimal('100')
    assert display[0][4] is True


# ── the suffixes that explain a line the total does not match ─────────────────

def test_account_line_marks_an_excluded_account():
    assert account_line('SoFi', 'Checking', '1234', Decimal('412'),
                        excluded=True) == \
        'SoFi · Checking ••1234: $412.00 (not counted)'


def test_account_line_marks_a_balance_discounted_for_unvested_equity():
    assert account_line('E*TRADE', 'Stock Plan', '7781', Decimal('84200'),
                        unvested_discounted=True) == \
        'E*TRADE · Stock Plan ••7781: $84,200.00 (unvested excluded)'


def test_account_line_combines_notes_in_one_parenthetical():
    assert account_line('SoFi', 'Checking', '1234', Decimal('412'),
                        stale=True, excluded=True) == \
        'SoFi · Checking ••1234: $412.00 (reconnect needed, not counted)'


def test_exclusion_suppresses_the_unvested_note():
    """An account contributing nothing need not explain how much was discounted."""
    line = account_line('E*TRADE', 'Stock Plan', '7781', Decimal('84200'),
                        excluded=True, unvested_discounted=True)
    assert line.endswith('(not counted)')


def test_digest_accounts_flags_only_accounts_with_unvested_equity():
    rows = [_row(unvested=Decimal('52800')), _row(unvested=None),
            _row(unvested=Decimal('0'))]
    assert [d[6] for d in digest_accounts(rows, [])[0]] == [True, False, False]


# ── the net-worth line in the message ─────────────────────────────────────────

def test_digest_body_closes_the_balances_block_with_net_worth():
    body = digest_body(TODAY, Decimal('750'), [
        ('Truist', 'Checking', '3390', Decimal('4880.02')),
    ], HISTORY, Decimal('4267.62'))
    assert 'Net worth: $4,267.62' in body
    assert body.index('Balances') < body.index('Truist · Checking') \
        < body.index('Net worth:') < body.index('Reply STOP')


def test_digest_body_omits_net_worth_when_nothing_is_linked():
    """`Net worth: $0.00` under "No linked accounts." is noise, not information."""
    body = digest_body(TODAY, Decimal('0'), [], HISTORY, Decimal('0'))
    assert 'Net worth' not in body


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
    for i, spec in enumerate(accounts):
        # (name, mask, balance[, type[, unvested_value]])
        acct_name, mask, balance = spec[:3]
        acct_type = spec[3] if len(spec) > 3 else 'depository'
        unvested = spec[4] if len(spec) > 4 else None
        db.session.add(Account(
            institution_id=inst.id, plaid_account_id=f'{name}-acct-{i}',
            name=acct_name, mask=mask, current_balance=balance,
            type=acct_type, unvested_value=unvested,
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


def _seed_txn(inst_id, txn_date, amount, category='FOOD_AND_DRINK'):
    db.session.add(Transaction(
        plaid_transaction_id=f'h-{txn_date}-{amount}', institution_id=inst_id,
        account_id='a1', date=txn_date, description='x',
        amount=Decimal(amount), category=category,
    ))
    db.session.commit()


def test_digest_history_is_built_from_real_transactions(app):
    """End to end: prior weeks bucket into the history, the current week does not."""
    with app.app_context():
        inst_id = _seed_inst('750.00')            # current week (Aug 2–8)
        _seed_txn(inst_id, date(2026, 7, 7), '842.00')    # Jul 5–11
        _seed_txn(inst_id, date(2026, 7, 30), '1204.00')  # Jul 26 – Aug 1
        _seed_txn(inst_id, date(2026, 6, 30), '999.00')   # before the window
        sender = FakeSender()
        send_daily_digest(db.session, TODAY,
                          {'BUDGET_ALERT_RECIPIENTS': '+1111'}, sender=sender)

        body = sender.sent[0][1]
        assert 'Jul 5–11: $842' in body
        assert 'Jul 12–18: $0' in body
        assert 'Jul 26 – Aug 1: $1,204' in body
        assert '$999' not in body                 # outside the four-week window
        assert 'Budget: $750 of $1,000' in body   # current week still its own line


def test_digest_history_still_costs_one_transaction_query(app):
    """Budget line and history come out of a single fetch, not one per week."""
    from sqlalchemy import event

    with app.app_context():
        _seed_inst('750.00')
        queries = []

        def record(conn, cursor, statement, params, context, executemany):
            if 'FROM transactions' in statement:
                queries.append(statement)

        engine = db.session.get_bind()
        event.listen(engine, 'before_cursor_execute', record)
        try:
            send_daily_digest(db.session, TODAY,
                              {'BUDGET_ALERT_RECIPIENTS': '+1111'},
                              sender=FakeSender())
        finally:
            event.remove(engine, 'before_cursor_execute', record)

        assert len(queries) == 1, queries


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


# ── net worth through the send paths ──────────────────────────────────────────

def _net_worth_cfg(excluded=''):
    return {'BUDGET_ALERT_RECIPIENTS': '+1111',
            'NET_WORTH_EXCLUDED_ACCOUNTS': excluded}


def test_scheduled_digest_nets_liabilities_off_assets(app):
    with app.app_context():
        _seed_inst('0.00', name='Truist',
                   accounts=[('Checking', '3390', Decimal('4880.02'))])
        _seed_inst(None, name='Citi',
                   accounts=[('Double Cash', '1234', Decimal('612.40'), 'credit')])
        sender = FakeSender()
        send_daily_digest(db.session, TODAY, _net_worth_cfg(), sender=sender)

        assert 'Net worth: $4,267.62' in sender.sent[0][1]


def test_scheduled_digest_honours_the_exclusion_list(app):
    with app.app_context():
        _seed_inst('0.00', name='Truist',
                   accounts=[('Checking', '3390', Decimal('4880.02'))])
        _seed_inst(None, name='SoFi',
                   accounts=[('Checking', '1234', Decimal('412.00'))])
        sender = FakeSender()
        send_daily_digest(db.session, TODAY,
                          _net_worth_cfg('sofi:checking'), sender=sender)

        body = sender.sent[0][1]
        assert 'SoFi · Checking ••1234: $412.00 (not counted)' in body
        assert 'Net worth: $4,880.02' in body


def test_unset_exclusion_list_counts_every_account(app):
    with app.app_context():
        _seed_inst('0.00', name='SoFi',
                   accounts=[('Checking', '1234', Decimal('412.00'))])
        sender = FakeSender()
        send_daily_digest(db.session, TODAY,
                          {'BUDGET_ALERT_RECIPIENTS': '+1111'}, sender=sender)

        body = sender.sent[0][1]
        assert 'Net worth: $412.00' in body
        assert 'not counted' not in body


def test_an_exclusion_that_matches_nothing_is_logged(app, caplog):
    """Silent no-match is the failure this feature cannot afford: the user
    believes an account is excluded and the total quietly disagrees."""
    with app.app_context():
        _seed_inst('0.00', name='Truist',
                   accounts=[('Checking', '3390', Decimal('10'))])
        sender = FakeSender()
        with caplog.at_level('WARNING'):
            send_daily_digest(db.session, TODAY,
                              _net_worth_cfg('sofi:checking'), sender=sender)

        assert 'NET_WORTH_EXCLUDED_ACCOUNTS matched no account' in caplog.text
        assert 'sofi:checking' in caplog.text
        assert 'Net worth: $10.00' in sender.sent[0][1]


def test_unvested_equity_is_netted_out_through_the_send_path(app):
    with app.app_context():
        _seed_inst('0.00', name='E*TRADE', accounts=[
            ('Stock Plan', '7781', Decimal('84200'), 'investment',
             Decimal('52800')),
        ])
        sender = FakeSender()
        send_daily_digest(db.session, TODAY, _net_worth_cfg(), sender=sender)

        body = sender.sent[0][1]
        assert 'E*TRADE · Stock Plan ••7781: $84,200.00 (unvested excluded)' in body
        assert 'Net worth: $31,400.00' in body


def test_manual_send_carries_the_same_net_worth_line(app):
    """The button and the 7am job build one message through one seam."""
    with app.app_context():
        _seed_inst('0.00', name='Truist',
                   accounts=[('Checking', '3390', Decimal('4880.02'))])
        _seed_inst(None, name='SoFi',
                   accounts=[('Checking', '1234', Decimal('412.00'))])
        sender = FakeSender()
        result = send_digest_now(db.session, TODAY,
                                 _net_worth_cfg('sofi:checking'), sender=sender)

        assert result['sent'] == ['+1111']
        body = sender.sent[0][1]
        assert 'SoFi · Checking ••1234: $412.00 (not counted)' in body
        assert 'Net worth: $4,880.02' in body
