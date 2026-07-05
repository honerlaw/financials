import threading
from datetime import date
from decimal import Decimal

from app.models import db, Institution, Transaction, BudgetAlert
from app.notifications import newly_crossed, send_budget_alerts


# 2026-07-08 is a Wednesday; its Sun–Sat week starts Jul 5 (a Sunday).
TODAY = date(2026, 7, 8)
WS = date(2026, 7, 5)


# ── newly_crossed (pure) ──────────────────────────────────────────────────────

def test_newly_crossed_at_exact_threshold():
    assert newly_crossed(50, []) == [50]


def test_newly_crossed_below_threshold():
    assert newly_crossed(49, []) == []


def test_newly_crossed_skips_already_sent():
    assert newly_crossed(80, [50]) == [75]


def test_newly_crossed_multi_threshold_jump():
    assert newly_crossed(105, []) == [50, 75, 100]


def test_newly_crossed_nothing_new_when_all_sent():
    assert newly_crossed(100, [50, 75, 100]) == []


# ── send_budget_alerts (orchestration) ────────────────────────────────────────

class FakeSender:
    """Records sends; optionally raises for specific recipients."""

    def __init__(self, fail_for=()):
        self.sent = []
        self.fail_for = set(fail_for)

    def send(self, to, body):
        if to in self.fail_for:
            raise RuntimeError('twilio down')
        self.sent.append((to, body))


def _seed_inst(week_total=None, txn_date=None):
    """Insert an institution and (optionally) one current-week transaction."""
    inst = Institution(name='B', slug='b', access_token='a', item_id='i')
    db.session.add(inst)
    db.session.commit()
    if week_total is not None:
        db.session.add(Transaction(
            plaid_transaction_id='t1', institution_id=inst.id, account_id='a1',
            date=txn_date or TODAY, description='x',
            amount=Decimal(week_total), category='FOOD_AND_DRINK',
        ))
        db.session.commit()
    return inst.id


def test_sends_each_crossed_threshold_to_each_recipient(app):
    with app.app_context():
        _seed_inst('750.00')  # 75% of $1000 → thresholds 50 and 75
        cfg = {'BUDGET_ALERT_RECIPIENTS': '+1111,+1222'}
        sender = FakeSender()
        send_budget_alerts(db.session, TODAY, cfg, sender=sender)
        # 2 thresholds × 2 recipients
        assert len(sender.sent) == 4
        assert BudgetAlert.query.count() == 4
        assert {r.threshold for r in BudgetAlert.query.all()} == {50, 75}
        # Message states the spend and percent.
        assert any('75%' in body and '750' in body for _, body in sender.sent)


def test_multi_threshold_jump_sends_all_three(app):
    with app.app_context():
        _seed_inst('1050.00')  # 105% → 50, 75, 100 in one run
        cfg = {'BUDGET_ALERT_RECIPIENTS': '+1111'}
        sender = FakeSender()
        send_budget_alerts(db.session, TODAY, cfg, sender=sender)
        assert len(sender.sent) == 3
        assert {r.threshold for r in BudgetAlert.query.all()} == {50, 75, 100}


def test_idempotent_second_run_sends_nothing(app):
    with app.app_context():
        _seed_inst('600.00')  # 60% → threshold 50
        cfg = {'BUDGET_ALERT_RECIPIENTS': '+1111'}
        first = FakeSender()
        send_budget_alerts(db.session, TODAY, cfg, sender=first)
        assert len(first.sent) == 1
        second = FakeSender()
        send_budget_alerts(db.session, TODAY, cfg, sender=second)
        assert second.sent == []
        assert BudgetAlert.query.filter_by(recipient='+1111').count() == 1


def test_noop_when_no_recipients(app):
    with app.app_context():
        _seed_inst('900.00')
        sender = FakeSender()
        send_budget_alerts(db.session, TODAY, {'BUDGET_ALERT_RECIPIENTS': ''},
                           sender=sender)
        assert sender.sent == []
        assert BudgetAlert.query.count() == 0


def test_noop_when_credentials_missing_and_no_injected_sender(app):
    with app.app_context():
        _seed_inst('900.00')
        # Recipients set, but no TWILIO_* creds and no injected sender → disabled.
        send_budget_alerts(db.session, TODAY, {'BUDGET_ALERT_RECIPIENTS': '+1111'})
        assert BudgetAlert.query.count() == 0


def test_failed_send_is_not_recorded_and_retries(app):
    with app.app_context():
        _seed_inst('600.00')  # 60% → threshold 50
        cfg = {'BUDGET_ALERT_RECIPIENTS': '+1111'}
        failing = FakeSender(fail_for={'+1111'})
        # Must not raise even though the send fails.
        send_budget_alerts(db.session, TODAY, cfg, sender=failing)
        assert BudgetAlert.query.count() == 0  # unrecorded → retryable
        working = FakeSender()
        send_budget_alerts(db.session, TODAY, cfg, sender=working)
        assert len(working.sent) == 1
        assert BudgetAlert.query.count() == 1


def test_concurrent_calls_do_not_double_send(tmp_path):
    """Two overlapping syncs must not double-text a threshold.

    Uses a file-backed SQLite DB so the two threads share one database (the
    module-level lock is what must serialize them). 600/1000 = 60% → only
    threshold 50 should ever be sent, exactly once.
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
            send_budget_alerts(_db.session, TODAY, cfg, sender=sender)
            _db.session.remove()

    threads = [threading.Thread(target=worker) for _ in range(2)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()

    with app.app_context():
        assert len(sender.sent) == 1
        assert BudgetAlert.query.filter_by(recipient='+1111').count() == 1
