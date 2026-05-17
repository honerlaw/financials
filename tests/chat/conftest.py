from datetime import date
from decimal import Decimal

import pytest

from app.models import db, Institution, Transaction


@pytest.fixture
def seed_data(app):
    """Seed two institutions with a deterministic set of transactions.

    Covers:
    - Multiple months (Jan-Mar 2026) for monthly aggregation
    - Repeated merchants for top-merchants / recurring detection
    - A mix of inflow (+) and outflow (-) for net/cash-flow tests
    - One uncategorized row to exercise null handling
    """
    truist = Institution(
        name='Truist', slug='truist',
        access_token='tok-t', item_id='item-t',
    )
    amex = Institution(
        name='Amex', slug='amex',
        access_token='tok-a', item_id='item-a',
    )
    db.session.add_all([truist, amex])
    db.session.flush()

    rows = [
        # (institution, date, description, merchant, amount, category)
        (truist, date(2026, 1, 5),  'NETFLIX.COM',     'Netflix',     -15.99, 'Subscriptions'),
        (truist, date(2026, 2, 5),  'NETFLIX.COM',     'Netflix',     -15.99, 'Subscriptions'),
        (truist, date(2026, 3, 5),  'NETFLIX.COM',     'Netflix',     -15.99, 'Subscriptions'),
        (truist, date(2026, 1, 12), 'WHOLE FOODS',     'Whole Foods', -82.40, 'Groceries'),
        (truist, date(2026, 2, 14), 'WHOLE FOODS',     'Whole Foods', -91.10, 'Groceries'),
        (truist, date(2026, 3, 9),  'WHOLE FOODS',     'Whole Foods', -77.05, 'Groceries'),
        (amex,   date(2026, 1, 20), 'AMAZON.COM',      'Amazon',      -34.99, 'Shopping'),
        (amex,   date(2026, 2, 22), 'AMAZON.COM',      'Amazon',      -129.00, 'Shopping'),
        (amex,   date(2026, 3, 1),  'PAYROLL DEPOSIT', None,          4200.00, None),
        (amex,   date(2026, 3, 15), 'UBER EATS',       'Uber Eats',   -28.75, 'Dining'),
    ]

    for inst, dt, desc, merch, amt, cat in rows:
        db.session.add(Transaction(
            plaid_transaction_id=f'{inst.slug}-{dt.isoformat()}-{desc}',
            institution_id=inst.id,
            account_id=f'{inst.slug}-acct',
            date=dt,
            description=desc,
            merchant_name=merch,
            amount=Decimal(str(amt)),
            category=cat,
        ))
    db.session.commit()
    return {'truist': truist, 'amex': amex}
