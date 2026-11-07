from datetime import date, timedelta
from decimal import Decimal
from itertools import permutations

from app.models import db, Institution, Transaction, Account
from app.subscriptions import (
    _group_transactions, detect_subscriptions, detect_subscriptions_from_groups,
    merge_by_descriptor, normalize_merchant,
)

TODAY = date(2026, 6, 1)


class FakeTxn:
    """Minimal stand-in for a Transaction row — detection is a pure function."""

    def __init__(self, txn_date, amount='15.49', merchant_name=None,
                 description=None, merchant_entity_id=None,
                 institution_id=1, account_id='acc-1', removed=False,
                 category=None, category_detailed=None):
        self.date = txn_date
        self.amount = Decimal(amount)
        self.merchant_name = merchant_name
        # Real rows always carry the card descriptor, and it usually reads like
        # the merchant; a shared placeholder would make every fixture one
        # descriptor and merge unrelated merchants (merge_by_descriptor).
        self.description = description or merchant_name or 'CHARGE'
        self.merchant_entity_id = merchant_entity_id
        self.institution_id = institution_id
        self.account_id = account_id
        self.removed = removed
        self.category = category
        self.category_detailed = category_detailed


def monthly_txns(n, start=date(2026, 1, 5), **kwargs):
    """n charges on the 5th of consecutive months."""
    txns = []
    for i in range(n):
        month = start.month + i
        year = start.year + (month - 1) // 12
        month = (month - 1) % 12 + 1
        txns.append(FakeTxn(date(year, month, start.day), **kwargs))
    return txns


# ── Normalization & grouping ─────────────────────────────────────────────────

def test_normalize_strips_digits_punctuation_and_noise():
    assert normalize_merchant('NETFLIX.COM 866-579-7172') == 'netflix'
    assert normalize_merchant('Netflix') == 'netflix'


def test_merchant_name_variants_do_not_split_a_stream():
    txns = [
        FakeTxn(date(2026, 1, 5), merchant_name='Netflix', description='Netflix'),
        FakeTxn(date(2026, 2, 5), merchant_name=None,
                description='NETFLIX.COM 866-579-7172'),
        FakeTxn(date(2026, 3, 5), merchant_name=None,
                description='NETFLIX.COM 866-579-7172'),
        FakeTxn(date(2026, 4, 5), merchant_name='Netflix', description='Netflix'),
        FakeTxn(date(2026, 5, 5), merchant_name='Netflix', description='Netflix'),
    ]
    streams = detect_subscriptions(txns, TODAY)
    assert len(streams) == 1
    assert streams[0]['count'] == 5


def test_prefix_variants_merge():
    txns = (
        monthly_txns(3, merchant_name='Spotify')
        + monthly_txns(2, start=date(2026, 4, 5), merchant_name=None,
                       description='SPOTIFY USA 12345')
    )
    streams = detect_subscriptions(txns, TODAY)
    assert len(streams) == 1


def test_entity_id_groups_across_name_changes():
    txns = [
        FakeTxn(date(2026, 1, 5), merchant_name='Hulu', merchant_entity_id='ent-1'),
        FakeTxn(date(2026, 2, 5), merchant_name='Hulu LLC', merchant_entity_id='ent-1'),
        FakeTxn(date(2026, 3, 5), merchant_name='Hulu', merchant_entity_id='ent-1'),
        FakeTxn(date(2026, 4, 5), merchant_name='Hulu', merchant_entity_id='ent-1'),
    ]
    streams = detect_subscriptions(txns, TODAY)
    assert len(streams) == 1
    assert streams[0]['name'] == 'Hulu'


def test_card_switch_does_not_split_stream():
    txns = (
        monthly_txns(3, merchant_name='Netflix', institution_id=1, account_id='amex')
        + monthly_txns(2, start=date(2026, 4, 5), merchant_name='Netflix',
                       institution_id=2, account_id='citi')
    )
    streams = detect_subscriptions(txns, TODAY)
    assert len(streams) == 1
    assert streams[0]['active'] is True
    assert set(streams[0]['account_keys']) == {(1, 'amex'), (2, 'citi')}


# ── Cadence buckets ──────────────────────────────────────────────────────────

def test_weekly_cadence():
    start = date(2026, 4, 6)
    txns = [FakeTxn(start + timedelta(weeks=i), merchant_name='Gym') for i in range(8)]
    streams = detect_subscriptions(txns, TODAY)
    assert len(streams) == 1
    assert streams[0]['cadence'] == 'weekly'


def test_biweekly_cadence():
    start = date(2026, 3, 6)
    txns = [FakeTxn(start + timedelta(days=14 * i), amount='-2500.00',
                    merchant_name='Employer Payroll') for i in range(6)]
    streams = detect_subscriptions(txns, TODAY)
    assert streams[0]['cadence'] == 'biweekly'
    assert streams[0]['is_inflow'] is True


def test_monthly_cadence_with_day_jitter():
    # 5th, then 8th, then 3rd — day-of-month wobble stays monthly
    txns = [
        FakeTxn(date(2026, 1, 5), merchant_name='Netflix'),
        FakeTxn(date(2026, 2, 8), merchant_name='Netflix'),
        FakeTxn(date(2026, 3, 3), merchant_name='Netflix'),
        FakeTxn(date(2026, 4, 6), merchant_name='Netflix'),
        FakeTxn(date(2026, 5, 5), merchant_name='Netflix'),
    ]
    streams = detect_subscriptions(txns, TODAY)
    assert len(streams) == 1
    assert streams[0]['cadence'] == 'monthly'
    assert streams[0]['next_date'] == date(2026, 5, 5) + timedelta(days=30)


def test_quarterly_cadence():
    txns = [
        FakeTxn(date(2025, 6, 1), merchant_name='Water Utility'),
        FakeTxn(date(2025, 9, 1), merchant_name='Water Utility'),
        FakeTxn(date(2025, 12, 1), merchant_name='Water Utility'),
        FakeTxn(date(2026, 3, 1), merchant_name='Water Utility'),
    ]
    streams = detect_subscriptions(txns, TODAY)
    assert streams[0]['cadence'] == 'quarterly'
    assert streams[0]['active'] is True


def test_annual_needs_only_two_occurrences():
    txns = [
        FakeTxn(date(2025, 5, 20), amount='12.00', merchant_name='Domain Registrar'),
        FakeTxn(date(2026, 5, 20), amount='12.00', merchant_name='Domain Registrar'),
    ]
    streams = detect_subscriptions(txns, TODAY)
    assert len(streams) == 1
    assert streams[0]['cadence'] == 'annual'


def test_two_occurrences_not_enough_for_monthly():
    txns = monthly_txns(2, start=date(2026, 4, 5), merchant_name='Netflix')
    assert detect_subscriptions(txns, TODAY) == []


def test_irregular_gaps_rejected():
    # Frequent grocery runs: median gap may fall in a bucket, but the gaps
    # are irregular, so no stream is detected.
    days = [0, 3, 8, 10, 17, 19, 26]
    txns = [FakeTxn(date(2026, 4, 1) + timedelta(days=d), merchant_name='Kroger')
            for d in days]
    assert detect_subscriptions(txns, TODAY) == []


# ── Amounts ──────────────────────────────────────────────────────────────────

def test_amount_jitter_never_gates_detection():
    # Card-payment-style stream: wildly varying amounts still detected.
    amounts = ['500.00', '3000.00', '1200.00', '750.00', '2100.00']
    txns = [t for i, t in enumerate(
        monthly_txns(5, merchant_name='AmEx ePayment'))]
    for txn, amt in zip(txns, amounts):
        txn.amount = Decimal(amt)
    streams = detect_subscriptions(txns, TODAY)
    assert len(streams) == 1
    assert streams[0]['varies'] is True
    assert streams[0]['amount'] == Decimal('1200.00')  # median


def test_fixed_price_stream_has_no_varies_badge():
    streams = detect_subscriptions(
        monthly_txns(5, merchant_name='Netflix', amount='15.49'), TODAY)
    assert streams[0]['varies'] is False


def test_price_hike_does_not_set_varies():
    txns = monthly_txns(5, merchant_name='Netflix', amount='15.49')
    txns[-1].amount = Decimal('17.99')
    streams = detect_subscriptions(txns, TODAY)
    assert len(streams) == 1
    assert streams[0]['varies'] is False


# ── Active / inactive ────────────────────────────────────────────────────────

def test_active_within_inactive_boundary():
    # Monthly cadence: inactive only when overdue by > 1.5 x 30 = 45 days.
    txns = monthly_txns(4, merchant_name='Netflix')  # last charge Apr 5
    streams = detect_subscriptions(txns, date(2026, 4, 5) + timedelta(days=45))
    assert streams[0]['active'] is True


def test_inactive_past_boundary():
    txns = monthly_txns(4, merchant_name='Netflix')  # last charge Apr 5
    streams = detect_subscriptions(txns, date(2026, 4, 5) + timedelta(days=46))
    assert streams[0]['active'] is False


def test_removed_transactions_excluded():
    txns = monthly_txns(3, merchant_name='Netflix')
    for t in txns:
        t.removed = True
    assert detect_subscriptions(txns, TODAY) == []


def test_streams_sorted_active_first():
    active = monthly_txns(4, start=date(2026, 3, 5), merchant_name='Netflix',
                          amount='5.00')
    inactive = monthly_txns(4, start=date(2025, 8, 5), merchant_name='Old Gym',
                            amount='50.00')
    streams = detect_subscriptions(active + inactive, TODAY)
    assert [s['active'] for s in streams] == [True, False]


# ── Route ────────────────────────────────────────────────────────────────────

def _seed_recurring(app):
    with app.app_context():
        inst = Institution(name='Test Bank', slug='test_bank',
                           access_token='tok', item_id='item-1')
        db.session.add(inst)
        db.session.flush()
        db.session.add(Account(
            institution_id=inst.id, plaid_account_id='acc-1',
            name='Credit Card', mask='1234',
        ))
        # Relative to today: the route uses date.today(), so fixed dates
        # would eventually drift past the inactive boundary and flake.
        today = date.today()
        for i, d in enumerate([today - timedelta(days=60),
                               today - timedelta(days=30), today]):
            db.session.add(Transaction(
                plaid_transaction_id=f'txn-{i}', institution_id=inst.id,
                account_id='acc-1', date=d, description='Netflix',
                merchant_name='Netflix', amount=Decimal('15.49'),
            ))
        db.session.commit()


# /subscriptions now redirects to /recurring (login and redirect behaviour are
# pinned in tests/test_bills.py); these tests pin that every recurring outflow
# it used to show still renders there.

def test_recurring_page_renders_subscription_stream(auth_client, app):
    _seed_recurring(app)
    res = auth_client.get('/recurring')
    assert res.status_code == 200
    assert b'Netflix' in res.data
    assert b'Monthly' in res.data or b'monthly' in res.data
    assert b'15.49' in res.data
    assert b'Test Bank' in res.data


def test_recurring_page_renders_multi_account_labels(auth_client, app):
    # One stream split across two institutions/cards must render both
    # "Institution · Account" badges on the single row.
    with app.app_context():
        amex = Institution(name='AmEx', slug='amex',
                           access_token='tok-a', item_id='item-a')
        citi = Institution(name='Citi', slug='citi',
                           access_token='tok-c', item_id='item-c')
        db.session.add_all([amex, citi])
        db.session.flush()
        db.session.add_all([
            Account(institution_id=amex.id, plaid_account_id='acc-amex',
                    name='Platinum'),
            Account(institution_id=citi.id, plaid_account_id='acc-citi',
                    name='Double Cash'),
        ])
        today = date.today()
        rows = [
            (amex.id, 'acc-amex', today - timedelta(days=90)),
            (amex.id, 'acc-amex', today - timedelta(days=60)),
            (citi.id, 'acc-citi', today - timedelta(days=30)),
            (citi.id, 'acc-citi', today),
        ]
        for i, (inst_id, acct_id, d) in enumerate(rows):
            db.session.add(Transaction(
                plaid_transaction_id=f'txn-ma-{i}', institution_id=inst_id,
                account_id=acct_id, date=d, description='Netflix',
                merchant_name='Netflix', amount=Decimal('15.49'),
            ))
        db.session.commit()

    res = auth_client.get('/recurring')
    assert res.status_code == 200
    assert 'AmEx · Platinum'.encode() in res.data
    assert 'Citi · Double Cash'.encode() in res.data



# ── Descriptor merge: one merchant renamed by Plaid ───────────────────────────

RENAMED = 'PAYCO* CONTOSO SERVICES'


def _renamed_bill(old_entity=None, new_entity='ent-new', today=TODAY):
    """A monthly bill under one merchant name that Plaid later renamed: the old
    history ends two months back (so on its own it reads lapsed) and the new
    name has two charges (too few to be a stream on its own)."""
    old = [FakeTxn(today - timedelta(days=30 * i), amount='250.00',
                   merchant_name='Contoso Ltd', description=RENAMED,
                   merchant_entity_id=old_entity)
           for i in range(3, 12)]
    new = [FakeTxn(today - timedelta(days=30 * i), amount='250.00',
                   merchant_name='Fabrikam Inc', description=RENAMED,
                   merchant_entity_id=new_entity)
           for i in range(0, 2)]
    return old, new


def _canonical(groups):
    return sorted(sorted(id(t) for t in g) for g in groups)


def test_renamed_merchant_is_one_active_stream():
    old, new = _renamed_bill()
    streams = detect_subscriptions(old + new, TODAY)
    assert len(streams) == 1
    assert streams[0]['cadence'] == 'monthly'
    assert streams[0]['active'] is True
    assert streams[0]['count'] == 11
    assert streams[0]['name'] == 'Contoso Ltd'   # the longer-lived name


def test_without_merge_the_renamed_bill_splits():
    """The failure the merge fixes: grouping by name alone splits the bill into
    a lapsed stream and a fragment too short to be one."""
    old, new = _renamed_bill()
    assert len(_group_transactions(old + new)) == 2
    (lapsed,) = detect_subscriptions_from_groups([old], TODAY)
    assert lapsed['active'] is False
    assert detect_subscriptions_from_groups([new], TODAY) == []


def test_different_descriptors_stay_separate():
    old, new = _renamed_bill()
    for t in new:
        t.description = 'SOMEWHERE ELSE ENTIRELY'
    assert _canonical(merge_by_descriptor([old, new])) == _canonical([old, new])


def test_two_entity_ids_never_merge():
    old, new = _renamed_bill(old_entity='ent-old', new_entity='ent-new')
    assert _canonical(merge_by_descriptor([old, new])) == _canonical([old, new])


def test_a_bucket_with_two_entities_merges_nothing():
    """A no-entity group must not be attributed to one of two entities."""
    old, new = _renamed_bill(old_entity=None, new_entity='ent-new')
    other = [FakeTxn(TODAY - timedelta(days=400 + 30 * i), description=RENAMED,
                     merchant_name='Third Co', merchant_entity_id='ent-third')
             for i in range(3)]
    groups = [old, new, other]
    assert _canonical(merge_by_descriptor(groups)) == _canonical(groups)


def test_entity_group_and_name_group_merge():
    old, new = _renamed_bill(old_entity=None, new_entity='ent-new')
    assert len(merge_by_descriptor([old, new])) == 1


def test_overlapping_date_ranges_do_not_merge():
    """Two merchants charging concurrently are not a rename."""
    old, new = _renamed_bill()
    new.append(FakeTxn(TODAY - timedelta(days=200), description=RENAMED,
                       merchant_name='Fabrikam Inc'))
    assert _canonical(merge_by_descriptor([old, new])) == _canonical([old, new])


def test_charges_and_deposits_do_not_merge():
    old, new = _renamed_bill()
    for t in new:
        t.amount = -t.amount
    assert _canonical(merge_by_descriptor([old, new])) == _canonical([old, new])


def test_short_descriptors_never_merge():
    old, new = _renamed_bill()
    for t in old + new:
        t.description = 'ACH'
    assert _canonical(merge_by_descriptor([old, new])) == _canonical([old, new])


def test_three_sequential_names_chain_into_one():
    old, new = _renamed_bill()
    oldest = [FakeTxn(TODAY - timedelta(days=30 * i), amount='250.00',
                      merchant_name='First Name Inc', description=RENAMED)
              for i in range(12, 15)]
    assert len(merge_by_descriptor([old, new, oldest])) == 1


def test_merge_does_not_mutate_its_input():
    old, new = _renamed_bill()
    before = (list(old), list(new))
    merge_by_descriptor([old, new])
    assert (old, new) == before


def test_merge_is_independent_of_input_order():
    old, new = _renamed_bill()
    oldest = [FakeTxn(TODAY - timedelta(days=30 * i), amount='250.00',
                      merchant_name='First Name Inc', description=RENAMED)
              for i in range(12, 15)]
    unrelated = monthly_txns(3, merchant_name='Netflix', description='NETFLIX.COM')
    groups = [old, new, oldest, unrelated]
    results = {tuple(map(tuple, _canonical(merge_by_descriptor(list(p)))))
               for p in permutations(groups)}
    assert len(results) == 1


def test_a_concurrent_group_blocks_merging_on_its_side():
    """Two short groups inside a longer group's range are not a rename chain,
    even though they follow each other."""
    long_running = [FakeTxn(TODAY - timedelta(days=30 * i), description=RENAMED,
                            merchant_name='Northwind') for i in range(0, 12)]
    first = [FakeTxn(TODAY - timedelta(days=d), description=RENAMED,
                     merchant_name='Fabrikam Inc') for d in (200, 170)]
    second = [FakeTxn(TODAY - timedelta(days=140), description=RENAMED,
                      merchant_name='Contoso Ltd')]
    groups = [long_running, first, second]
    assert _canonical(merge_by_descriptor(groups)) == _canonical(groups)


def test_same_day_boundary_is_an_overlap():
    old, new = _renamed_bill()
    new.append(FakeTxn(max(t.date for t in old), description=RENAMED,
                       merchant_name='Fabrikam Inc'))
    assert _canonical(merge_by_descriptor([old, new])) == _canonical([old, new])


def test_renamed_deposits_merge_too():
    old, new = _renamed_bill()
    for t in old + new:
        t.amount = -t.amount
    assert len(merge_by_descriptor([old, new])) == 1


# ── Calendar-month regularity: a monthly bill paid by hand on a drifting day ──
# Fixed dates throughout (knowledge 004: the detector takes `today`), because
# the rule depends on which calendar month each date falls in.

from app.subscriptions import _classify_cadence, _gap_is_regular

MONTHLY = (30, 6)   # the monthly bucket's (nominal, tolerance)


def _drifting_bill_dates():
    """Once per calendar month, posting anywhere from the 5th to the 17th."""
    months = [(2025, 7), (2025, 8), (2025, 9), (2025, 10), (2025, 11),
              (2025, 12), (2026, 1), (2026, 2), (2026, 3), (2026, 4), (2026, 5)]
    days = [5, 17, 8, 16, 6, 15, 5, 17, 7, 16, 9]
    return [date(y, m, d) for (y, m), d in zip(months, days)]


def _old_rule_regular_fraction(dates):
    gaps = [(b - a).days for a, b in zip(dates, dates[1:])]
    return sum(1 for g in gaps if abs(g - 30) <= 6) / len(gaps)


def test_drifting_day_monthly_bill_is_one_active_monthly_stream():
    dates = _drifting_bill_dates()
    assert _old_rule_regular_fraction(dates) < 0.7     # the old rule dropped it
    txns = [FakeTxn(d, amount='512.00', merchant_name='Example Auto Loan')
            for d in dates]
    streams = detect_subscriptions(txns, TODAY)
    assert len(streams) == 1
    assert streams[0]['cadence'] == 'monthly'
    assert streams[0]['active'] is True
    assert streams[0]['count'] == len(dates)


def test_consecutive_month_gap_bounds_are_inclusive_15_and_45():
    start = date(2026, 1, 31)
    assert _gap_is_regular(start, start + timedelta(days=15), *MONTHLY)   # Feb 15
    assert not _gap_is_regular(start, start + timedelta(days=14), *MONTHLY)
    start = date(2026, 1, 1)
    assert _gap_is_regular(start, start + timedelta(days=45), *MONTHLY)   # Feb 15
    assert not _gap_is_regular(start, start + timedelta(days=46), *MONTHLY)


def test_consecutive_months_far_apart_are_not_regular():
    assert not _gap_is_regular(date(2026, 1, 2), date(2026, 2, 27), *MONTHLY)
    assert _gap_is_regular(date(2026, 1, 12), date(2026, 2, 21), *MONTHLY)


def test_a_gap_inside_one_month_is_not_regular():
    assert not _gap_is_regular(date(2026, 3, 3), date(2026, 3, 23), *MONTHLY)
    assert _gap_is_regular(date(2026, 3, 23), date(2026, 4, 12), *MONTHLY)


def test_a_gap_that_skips_a_month_is_not_regular():
    assert not _gap_is_regular(date(2026, 1, 30), date(2026, 3, 13), *MONTHLY)
    # The same 42 days between consecutive months is regular.
    assert _gap_is_regular(date(2026, 1, 1), date(2026, 2, 12), *MONTHLY)


def test_december_to_january_counts_as_consecutive():
    assert _gap_is_regular(date(2025, 12, 5), date(2026, 1, 12), *MONTHLY)


def test_the_calendar_rule_applies_only_to_the_monthly_bucket():
    # 20 days across a month boundary is regular for neither biweekly nor
    # quarterly, whatever the calendar says.
    assert not _gap_is_regular(date(2026, 1, 25), date(2026, 2, 14), 14, 3)
    assert not _gap_is_regular(date(2026, 1, 25), date(2026, 2, 14), 91, 12)


def test_irregular_monthly_ish_visits_are_not_monthly():
    """Median gap ~30, so the monthly bucket is chosen and the calendar rule
    itself decides: visits bunch inside one month, then skip the next."""
    dates = [date(2025, 9, 2), date(2025, 9, 22), date(2025, 11, 1),
             date(2025, 12, 1), date(2025, 12, 23), date(2026, 2, 1),
             date(2026, 3, 3), date(2026, 3, 24), date(2026, 5, 2)]
    gaps = [(b - a).days for a, b in zip(dates, dates[1:])]
    assert 24 <= sorted(gaps)[len(gaps) // 2] <= 36
    assert _classify_cadence(dates) is None
    txns = [FakeTxn(d, amount='40.00', merchant_name='Corner Shop') for d in dates]
    assert detect_subscriptions(txns, TODAY) == []


def test_three_consecutive_months_with_drifting_gaps_is_monthly():
    """Accepted short-history trade-off: gaps of 18 and 42 days in three
    consecutive months read as monthly (the old rule rejected them)."""
    dates = [date(2026, 3, 28), date(2026, 4, 15), date(2026, 5, 27)]
    assert _old_rule_regular_fraction(dates) == 0
    assert _classify_cadence(dates) == ('monthly', 30)
