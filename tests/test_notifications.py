import threading
from datetime import date

import pytest
from decimal import Decimal

from sqlalchemy.exc import OperationalError

from app.models import db, Account, Institution, Transaction, DailyDigest
from app.notifications import (
    AccountRow, account_line, budget_line, card_total_line, category_name,
    digest_body, digest_cards, history_line, send_daily_digest,
    send_digest_now, yesterday_lines,
)
from app.spending import DaySpend


# 2026-08-08 is a Saturday; its Sun–Sat week starts Aug 2 (a Sunday).
TODAY = date(2026, 8, 8)
WS = date(2026, 8, 2)
YESTERDAY = date(2026, 8, 7)
# The four completed weeks behind it, oldest first — what recent_week_spend
# hands digest_body.
HISTORY = [
    (date(2026, 7, 5), Decimal('842')),
    (date(2026, 7, 12), Decimal('1130')),
    (date(2026, 7, 19), Decimal('0')),
    (date(2026, 7, 26), Decimal('1204')),
]
NO_SPEND = DaySpend(YESTERDAY, 0, Decimal('0'), [], [])
CARDS = [
    ('Amex', 'Gold Card', '1008', Decimal('1204.33')),
    ('Citi', 'Double Cash', '1234', Decimal('612.40')),
]


def _body(cards=CARDS, card_total=Decimal('1816.73'), yesterday=NO_SPEND,
          spent=Decimal('750'), history=HISTORY):
    return digest_body(TODAY, spent, history, cards, card_total, yesterday)


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
    assert account_line('Citi', 'Double Cash', '1234', Decimal('612.40')) == \
        'Citi · Double Cash ••1234: $612.40'


def test_account_line_without_mask():
    assert account_line('Amex', 'Platinum', None, Decimal('12.00')) == \
        'Amex · Platinum: $12.00'


def test_account_line_null_balance_renders_dash():
    assert account_line('Citi', 'New Card', '8821', None) == 'Citi · New Card ••8821: —'


def test_account_line_prints_a_negative_card_balance_as_the_dashboard_does():
    """An overpaid card carries a credit; the line prints the raw balance."""
    assert account_line('Citi', 'Card', '8821', Decimal('-12.34')) == \
        'Citi · Card ••8821: $-12.34'


def test_account_line_flags_a_bank_that_stopped_syncing():
    """A non-active institution is skipped by the sync, so its balance is frozen —
    the text must say so rather than present a stale number as current."""
    assert account_line('Citi', 'Card', '8821', Decimal('10'), stale=True) == \
        'Citi · Card ••8821: $10.00 (reconnect needed)'


def test_digest_body_contains_budget_week_and_every_card():
    body = _body()
    assert body.startswith('Onerlaw LLC\nGood morning — Sat Aug 8')
    assert 'Budget: $750 of $1,000 (75%) — $250 left' in body
    assert 'Week of Aug 2' in body
    assert 'Amex · Gold Card ••1008: $1,204.33' in body
    assert 'Citi · Double Cash ••1234: $612.40' in body


@pytest.mark.parametrize('cards', [[], CARDS])
def test_digest_body_is_branded_and_carries_opt_out(cards):
    """A2P 10DLC registration requires the business name and opt-out language in
    the body, and carrier traffic has to match the samples filed with the
    campaign — so this holds whether or not any card is linked."""
    body = _body(cards=cards)
    assert body.startswith('Onerlaw LLC\n')
    assert body.endswith('\nReply STOP to unsubscribe.')


def test_history_line_formats_a_week_in_whole_dollars():
    assert history_line(date(2026, 7, 5), Decimal('842.47')) == 'Jul 5–11: $842'
    assert history_line(date(2026, 7, 26), Decimal('1204')) == 'Jul 26 – Aug 1: $1,204'


def test_digest_body_lists_the_four_completed_weeks_oldest_first():
    body = _body()
    assert 'Last 4 weeks' in body
    for expected in ('Jul 5–11: $842', 'Jul 12–18: $1,130',
                     'Jul 19–25: $0', 'Jul 26 – Aug 1: $1,204'):
        assert expected in body
    assert body.index('Jul 5–11') < body.index('Jul 12–18') \
        < body.index('Jul 19–25') < body.index('Jul 26 – Aug 1')


def test_digest_body_orders_budget_history_cards_then_yesterday():
    body = _body()
    assert body.index('Week of Aug 2') < body.index('Last 4 weeks') \
        < body.index('Credit cards') < body.index('Yesterday — Fri Aug 7') \
        < body.index('Reply STOP')


def test_digest_body_history_never_repeats_the_current_week():
    """The running week is the budget line's job; a partial week in a column of
    finished ones reads as a drop that is not real."""
    assert 'Aug 2–8' not in _body()


# ── credit cards (pure) ───────────────────────────────────────────────────────

def _row(institution='Citi', account='Double Cash', mask='1234',
         balance=Decimal('612.40'), status='active', type='credit'):
    return AccountRow(institution, account, mask, balance, status, type)


def test_digest_cards_keeps_only_credit_accounts_and_sums_them():
    rows = [
        _row('Truist', 'Checking', '3390', Decimal('4880.02'), type='depository'),
        _row('SoFi', 'Savings', '7742', Decimal('412.00'), type='depository'),
        _row('E*TRADE', 'Stock Plan', '7781', Decimal('84200'), type='investment'),
        _row('Truist', 'Mortgage', '9902', Decimal('250000'), type='loan'),
        _row('Amex', 'Gold Card', '1008', Decimal('1204.33')),
        _row('Citi', 'Double Cash', '1234', Decimal('612.40')),
        _row('New', 'Account', '0001', Decimal('5'), type=None),
    ]
    display, total = digest_cards(rows)
    assert [d[1] for d in display] == ['Gold Card', 'Double Cash']
    assert total == Decimal('1816.73')


def test_card_type_matching_is_case_insensitive():
    display, _ = digest_cards([_row(type='CREDIT')])
    assert len(display) == 1


def test_a_null_card_balance_is_listed_but_adds_nothing():
    display, total = digest_cards([_row(balance=None),
                                   _row(account='Gold', balance=Decimal('10'))])
    assert len(display) == 2
    assert total == Decimal('10')


def test_a_stale_card_is_flagged_and_still_counted():
    display, total = digest_cards([_row(status='login_required')])
    assert display[0][4] is True
    assert total == Decimal('612.40')


def test_an_overpaid_card_reduces_the_total():
    _, total = digest_cards([_row(balance=Decimal('100')),
                             _row(account='Gold', balance=Decimal('-120.50'))])
    assert total == Decimal('-20.50')


def test_card_total_line_formats_dollars_and_cents():
    assert card_total_line(Decimal('1816.73')) == 'Total card debt: $1,816.73'


def test_card_total_line_puts_the_minus_before_the_dollar_sign():
    assert card_total_line(Decimal('-20.50')) == 'Total card debt: -$20.50'


def test_digest_body_lists_only_cards_and_closes_with_their_total():
    """Other account types and net worth are gone from the message."""
    rows = [
        _row('Truist', 'Checking', '3390', Decimal('4880.02'), type='depository'),
        _row('Truist', 'Mortgage', '9902', Decimal('250000'), type='loan'),
        _row('Amex', 'Gold Card', '1008', Decimal('1204.33')),
        _row('Citi', 'Double Cash', '1234', Decimal('612.40')),
    ]
    cards, total = digest_cards(rows)
    body = _body(cards=cards, card_total=total)
    assert ('Credit cards\n'
            'Amex · Gold Card ••1008: $1,204.33\n'
            'Citi · Double Cash ••1234: $612.40\n'
            'Total card debt: $1,816.73\n') in body
    assert 'Checking' not in body and 'Mortgage' not in body
    assert 'Net worth' not in body
    assert 'Balances' not in body


def test_digest_body_without_cards_says_so_and_prints_no_total():
    body = _body(cards=[], card_total=Decimal('0'))
    assert 'Credit cards\nNo linked credit cards.\n' in body
    assert 'Total card debt' not in body


# ── yesterday (pure) ──────────────────────────────────────────────────────────

def _spend(count=3, total=Decimal('287.40'), large=(), by_category=()):
    return DaySpend(YESTERDAY, count, total, list(large), list(by_category))


def test_category_name_humanizes_the_plaid_primary():
    assert category_name('FOOD_AND_DRINK') == 'Food and drink'
    assert category_name('GENERAL_MERCHANDISE') == 'General merchandise'
    assert category_name(None) == 'Uncategorized'


def test_yesterday_section_with_purchases():
    lines = yesterday_lines(_spend(
        count=6, total=Decimal('287.40'),
        large=[('Whole Foods Market', Decimal('142.18'))],
        by_category=[('FOOD_AND_DRINK', Decimal('201.30')),
                     ('GENERAL_MERCHANDISE', Decimal('86.10'))],
    ))
    assert lines == [
        'Yesterday — Fri Aug 7',
        '6 purchases: $287',
        'Over $100',
        'Whole Foods Market: $142.18',
        'By category',
        'Food and drink: $201',
        'General merchandise: $86',
    ]


def test_yesterday_section_with_one_purchase_uses_the_singular():
    lines = yesterday_lines(_spend(
        count=1, total=Decimal('40'), by_category=[(None, Decimal('40'))]))
    assert lines[1] == '1 purchase: $40'
    assert lines[-1] == 'Uncategorized: $40'


def test_yesterday_section_with_nothing_over_100():
    lines = yesterday_lines(_spend(
        by_category=[('FOOD_AND_DRINK', Decimal('287.40'))]))
    assert 'Over $100: none' in lines
    assert 'Over $100' not in lines


def test_yesterday_section_with_no_purchases():
    assert yesterday_lines(NO_SPEND) == [
        'Yesterday — Fri Aug 7', 'No purchases.',
    ]


def test_the_large_purchase_list_is_capped_with_a_count_of_the_rest():
    large = [(f'Shop {i}', Decimal(500 - i)) for i in range(13)]
    lines = yesterday_lines(_spend(large=large))
    start = lines.index('Over $100') + 1
    end = lines.index('By category')
    shown = lines[start:end]
    assert len(shown) == 11
    assert shown[0] == 'Shop 0: $500.00'
    assert shown[-1] == '+3 more'


def test_a_long_merchant_label_is_truncated():
    label = 'A' * 50
    lines = yesterday_lines(_spend(large=[(label, Decimal('150'))]))
    line = next(l for l in lines if l.endswith(': $150.00'))
    name = line[:-len(': $150.00')]
    assert len(name) == 32
    assert name.endswith('…')


def test_the_category_list_is_capped_with_an_other_line():
    cats = [(f'CAT_{i}', Decimal(100 - i)) for i in range(8)]
    lines = yesterday_lines(_spend(by_category=cats))
    shown = lines[lines.index('By category') + 1:]
    assert len(shown) == 6
    assert shown[:5] == ['Cat 0: $100', 'Cat 1: $99', 'Cat 2: $98',
                         'Cat 3: $97', 'Cat 4: $96']
    assert shown[5] == 'Other: $282'   # 95 + 94 + 93


def test_six_categories_are_shown_without_an_other_line():
    cats = [(f'CAT_{i}', Decimal(10)) for i in range(6)]
    lines = yesterday_lines(_spend(by_category=cats))
    assert not any(l.startswith('Other') for l in lines)


def test_a_worst_case_digest_stays_under_twilios_length_limit():
    """Twilio rejects a body over 1600 characters, losing the day's digest."""
    cards = [(f'Institution {i}', f'Rewards Card {i}', f'{1000 + i}',
              Decimal('12345.67')) for i in range(8)]
    large = [('M' * 60, Decimal('9999.99')) for _ in range(15)]
    cats = [('RENT_AND_UTILITIES_' + str(i), Decimal('99999')) for i in range(12)]
    body = _body(cards=cards, card_total=Decimal('98765.36'),
                 yesterday=_spend(count=99, total=Decimal('99999'),
                                  large=large, by_category=cats),
                 spent=Decimal('99999'))
    assert len(body) < 1600, len(body)


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
        # (name, mask, balance[, type])
        acct_name, mask, balance = spec[:3]
        acct_type = spec[3] if len(spec) > 3 else 'depository'
        db.session.add(Account(
            institution_id=inst.id, plaid_account_id=f'{name}-acct-{i}',
            name=acct_name, mask=mask, current_balance=balance,
            type=acct_type,
        ))
    db.session.commit()
    return inst.id


def test_sends_one_digest_to_each_recipient(app):
    with app.app_context():
        _seed_inst('750.00', accounts=[
            ('Double Cash', '1234', Decimal('612.40'), 'credit')])
        cfg = {'BUDGET_ALERT_RECIPIENTS': '+1111,+1222'}
        sender = FakeSender()
        send_daily_digest(db.session, TODAY, cfg, sender=sender)

        assert len(sender.sent) == 2
        assert {to for to, _ in sender.sent} == {'+1111', '+1222'}
        assert DailyDigest.query.count() == 2
        assert {r.sent_date for r in DailyDigest.query.all()} == {TODAY}
        # Both budget status and card balances ride in the one message.
        body = sender.sent[0][1]
        assert '75%' in body and '$750' in body
        assert 'B · Double Cash ••1234: $612.40' in body


def test_digest_lists_every_card_ordered_by_institution(app):
    with app.app_context():
        _seed_inst('0.00', name='Zeta', accounts=[
            ('Savor', '1111', Decimal('10'), 'credit')])
        _seed_inst(None, name='Alpha', accounts=[
            ('Gold', '2222', Decimal('20'), 'credit'),
            ('Blue', '3333', None, 'credit'),  # null balance still listed
        ])
        sender = FakeSender()
        send_daily_digest(db.session, TODAY,
                          {'BUDGET_ALERT_RECIPIENTS': '+1111'}, sender=sender)

        body = sender.sent[0][1]
        assert 'Alpha · Blue ••3333: —' in body
        assert body.index('Alpha · Blue') < body.index('Alpha · Gold') \
            < body.index('Zeta · Savor')
        assert 'Total card debt: $30.00' in body


def test_digest_flags_accounts_of_a_bank_needing_reconnect(app):
    """sync_all_institutions only syncs status='active', so a login_required
    bank's balance is frozen at its last good sync — the digest must not present
    it as current."""
    with app.app_context():
        _seed_inst('0.00', name='Stale', status='login_required',
                   accounts=[('Card', '9999', Decimal('42'), 'credit')])
        _seed_inst(None, name='Fresh', accounts=[
            ('Card', '1111', Decimal('7'), 'credit')])
        sender = FakeSender()
        send_daily_digest(db.session, TODAY,
                          {'BUDGET_ALERT_RECIPIENTS': '+1111'}, sender=sender)

        body = sender.sent[0][1]
        assert 'Stale · Card ••9999: $42.00 (reconnect needed)' in body
        assert 'Fresh · Card ••1111: $7.00' in body
        assert 'Fresh · Card ••1111: $7.00 (reconnect' not in body


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
        _seed_inst('750.00', accounts=[
            ('Double Cash', '1234', Decimal('612.40'), 'credit')])
        sender = FakeSender()
        result = send_digest_now(db.session, TODAY,
                                 {'BUDGET_ALERT_RECIPIENTS': '+1111,+1222'},
                                 sender=sender)
        assert result == {'configured': True, 'sent': ['+1111', '+1222'], 'failed': []}
        assert len(sender.sent) == 2
        body = sender.sent[0][1]
        assert '75%' in body
        assert 'B · Double Cash ••1234: $612.40' in body
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


# ── cards and yesterday through the send paths ────────────────────────────────

CFG = {'BUDGET_ALERT_RECIPIENTS': '+1111'}


def _seed_yesterday(inst_id):
    """Yesterday's purchases plus the rows the section must ignore."""
    rows = [
        ('y1', YESTERDAY, '142.18', 'FOOD_AND_DRINK', 'Whole Foods Market'),
        ('y2', YESTERDAY, '59.12', 'FOOD_AND_DRINK', 'Chipotle'),
        ('y3', YESTERDAY, '86.10', 'GENERAL_MERCHANDISE', 'Target'),
        ('y4', YESTERDAY, '1500.00', 'TRANSFER_OUT', 'Card payment'),
        ('y5', YESTERDAY, '-40.00', 'GENERAL_MERCHANDISE', 'Refund'),
        ('t1', TODAY, '230.00', 'TRAVEL', 'Delta'),
        ('o1', date(2026, 8, 5), '400.00', 'TRAVEL', 'Hotel'),
    ]
    for pid, d, amount, category, merchant in rows:
        db.session.add(Transaction(
            plaid_transaction_id=pid, institution_id=inst_id, account_id='a1',
            date=d, description=merchant.upper(), merchant_name=merchant,
            amount=Decimal(amount), category=category,
        ))
    db.session.add(Transaction(
        plaid_transaction_id='gone', institution_id=inst_id, account_id='a1',
        date=YESTERDAY, description='x', amount=Decimal('999'),
        category='FOOD_AND_DRINK', removed=True,
    ))
    db.session.commit()


def test_scheduled_digest_lists_only_cards_with_their_total(app):
    with app.app_context():
        _seed_inst('0.00', name='Truist', accounts=[
            ('Checking', '3390', Decimal('4880.02')),
            ('Mortgage', '9902', Decimal('250000'), 'loan'),
        ])
        _seed_inst(None, name='Citi',
                   accounts=[('Double Cash', '1234', Decimal('612.40'), 'credit')])
        _seed_inst(None, name='Amex',
                   accounts=[('Gold Card', '1008', Decimal('1204.33'), 'credit')])
        sender = FakeSender()
        send_daily_digest(db.session, TODAY, CFG, sender=sender)

        body = sender.sent[0][1]
        assert ('Credit cards\n'
                'Amex · Gold Card ••1008: $1,204.33\n'
                'Citi · Double Cash ••1234: $612.40\n'
                'Total card debt: $1,816.73\n') in body
        assert 'Checking' not in body and 'Mortgage' not in body
        assert 'Net worth' not in body


def test_scheduled_digest_reports_yesterday_from_real_transactions(app):
    with app.app_context():
        inst_id = _seed_inst(None)
        _seed_yesterday(inst_id)
        sender = FakeSender()
        send_daily_digest(db.session, TODAY, CFG, sender=sender)

        body = sender.sent[0][1]
        assert ('Yesterday — Fri Aug 7\n'
                '3 purchases: $287\n'
                'Over $100\n'
                'Whole Foods Market: $142.18\n'
                'By category\n'
                'Food and drink: $201\n'
                'General merchandise: $86\n') in body
        assert 'Delta' not in body and 'Hotel' not in body


def test_manual_send_carries_the_same_cards_and_yesterday(app):
    with app.app_context():
        inst_id = _seed_inst(None, name='Citi', accounts=[
            ('Double Cash', '1234', Decimal('612.40'), 'credit')])
        _seed_yesterday(inst_id)
        manual = FakeSender()
        send_digest_now(db.session, TODAY, CFG, sender=manual)
        scheduled = FakeSender()
        send_daily_digest(db.session, TODAY, CFG, sender=scheduled)

        body = manual.sent[0][1]
        assert 'Total card debt: $612.40' in body
        assert 'Whole Foods Market: $142.18' in body
        assert scheduled.sent[0][1] == body


def test_yesterday_on_a_sunday_reaches_back_into_last_week(app):
    """Sunday's yesterday is the Saturday before this week starts — still inside
    the one fetch, which reaches back four whole weeks."""
    with app.app_context():
        inst_id = _seed_inst(None)
        _seed_txn(inst_id, TODAY, '123.45')       # Sat Aug 8
        sender = FakeSender()
        send_daily_digest(db.session, date(2026, 8, 9), CFG, sender=sender)

        body = sender.sent[0][1]
        assert 'Yesterday — Sat Aug 8\n1 purchase: $123' in body
        assert 'x: $123.45' in body


def test_a_purchase_is_reported_once_across_its_pending_and_posted_rows(app):
    """Bought Fri, reported pending in Saturday's text; it posts Monday with the
    same authorized_date, so Tuesday's "Yesterday — Mon" must not repeat it.
    A posted row Plaid gives no authorized_date falls back to its posting date
    (the accepted residual)."""
    with app.app_context():
        inst_id = _seed_inst(None)
        db.session.add(Transaction(
            plaid_transaction_id='pend', institution_id=inst_id, account_id='a1',
            date=YESTERDAY, authorized_date=YESTERDAY, description='SHOP',
            merchant_name='Pending Shop', amount=Decimal('150.00'),
            category='GENERAL_MERCHANDISE', pending=True,
        ))
        db.session.commit()
        saturday = FakeSender()
        send_digest_now(db.session, TODAY, CFG, sender=saturday)
        assert 'Pending Shop: $150.00' in saturday.sent[0][1]

        # Monday's sync: the pending row is removed, the posted row arrives.
        pending = Transaction.query.filter_by(plaid_transaction_id='pend').one()
        pending.removed = True
        monday = date(2026, 8, 10)
        db.session.add(Transaction(
            plaid_transaction_id='post', institution_id=inst_id, account_id='a1',
            date=monday, authorized_date=YESTERDAY, description='SHOP',
            merchant_name='Pending Shop', amount=Decimal('150.00'),
            category='GENERAL_MERCHANDISE', pending_transaction_id='pend',
        ))
        db.session.add(Transaction(
            plaid_transaction_id='noauth', institution_id=inst_id,
            account_id='a1', date=monday, authorized_date=None,
            description='CAFE', merchant_name='No Auth Cafe',
            amount=Decimal('120.00'), category='FOOD_AND_DRINK',
        ))
        db.session.commit()
        tuesday = FakeSender()
        send_digest_now(db.session, date(2026, 8, 11), CFG, sender=tuesday)

        body = tuesday.sent[0][1]
        assert 'Yesterday — Mon Aug 10\n1 purchase: $120' in body
        assert 'Pending Shop' not in body
        assert 'No Auth Cafe: $120.00' in body

