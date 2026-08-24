from datetime import datetime, timezone
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.types import JSON

from app import db


# JSONB on Postgres, JSON on SQLite (used by the test suite).
JSONType = JSON().with_variant(JSONB(), 'postgresql')


def _utcnow():
    return datetime.now(timezone.utc)


class Institution(db.Model):
    __tablename__ = 'institutions'

    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(255), nullable=False)
    slug = db.Column(db.String(255), unique=True, nullable=False)
    access_token = db.Column(db.String(255), nullable=False)
    item_id = db.Column(db.String(255), unique=True, nullable=False)
    plaid_cursor = db.Column(db.Text, default='', nullable=False)
    status = db.Column(db.String(50), default='active', nullable=False)
    last_synced_at = db.Column(db.DateTime(timezone=True), nullable=True)
    created_at = db.Column(db.DateTime(timezone=True), default=_utcnow, nullable=False)

    transactions = db.relationship(
        'Transaction', backref='institution', lazy=True, cascade='all, delete-orphan'
    )
    sync_logs = db.relationship(
        'SyncLog', backref='institution', lazy=True, passive_deletes=True
    )
    accounts = db.relationship(
        'Account', backref='institution', lazy=True, cascade='all, delete-orphan'
    )


class Account(db.Model):
    __tablename__ = 'accounts'

    id = db.Column(db.Integer, primary_key=True)
    institution_id = db.Column(
        db.Integer, db.ForeignKey('institutions.id', ondelete='CASCADE'), nullable=False
    )
    plaid_account_id = db.Column(db.String(255), unique=True, nullable=False)
    name = db.Column(db.String(255), nullable=False)
    official_name = db.Column(db.String(255), nullable=True)
    mask = db.Column(db.String(8), nullable=True)
    type = db.Column(db.String(50), nullable=True)
    subtype = db.Column(db.String(50), nullable=True)
    current_balance = db.Column(db.Numeric(12, 2), nullable=True)
    available_balance = db.Column(db.Numeric(12, 2), nullable=True)
    iso_currency_code = db.Column(db.String(10), nullable=True)
    # Liability fields, populated from Plaid's /liabilities/get for credit,
    # student, and mortgage accounts. Null for depository accounts (and for any
    # Item not consented to the `liabilities` product). See
    # .minerva/knowledge/014-decision-plaid-liabilities-piggyback-on-sync.md.
    next_payment_due_date = db.Column(db.Date, nullable=True)
    last_statement_balance = db.Column(db.Numeric(12, 2), nullable=True)
    minimum_payment_amount = db.Column(db.Numeric(12, 2), nullable=True)
    # Equity-compensation totals, populated from Plaid's
    # /investments/holdings/get. Null unless the account holds equity comp the
    # institution reports a vested figure for (so: null for depository
    # accounts, for plain brokerage accounts, and for any Item not consented to
    # the `investments` product). See
    # .minerva/knowledge/021-decision-plaid-vested-value-piggyback-on-sync.md.
    vested_value = db.Column(db.Numeric(12, 2), nullable=True)
    unvested_value = db.Column(db.Numeric(12, 2), nullable=True)
    last_synced_at = db.Column(db.DateTime(timezone=True), nullable=True)
    created_at = db.Column(db.DateTime(timezone=True), default=_utcnow, nullable=False)


class Transaction(db.Model):
    __tablename__ = 'transactions'

    id = db.Column(db.Integer, primary_key=True)
    plaid_transaction_id = db.Column(db.String(255), unique=True, nullable=False)
    institution_id = db.Column(
        db.Integer, db.ForeignKey('institutions.id', ondelete='CASCADE'), nullable=False
    )
    account_id = db.Column(db.String(255), nullable=False)
    date = db.Column(db.Date, nullable=False)
    authorized_date = db.Column(db.Date, nullable=True)
    description = db.Column(db.String(512), nullable=False)
    original_description = db.Column(db.String(512), nullable=True)
    merchant_name = db.Column(db.String(255), nullable=True)
    merchant_entity_id = db.Column(db.String(255), nullable=True)
    website = db.Column(db.String(512), nullable=True)
    amount = db.Column(db.Numeric(10, 2), nullable=False)
    iso_currency_code = db.Column(db.String(10), nullable=True)
    category = db.Column(db.String(255), nullable=True)
    category_detailed = db.Column(db.String(255), nullable=True)
    category_confidence = db.Column(db.String(50), nullable=True)
    payment_channel = db.Column(db.String(50), nullable=True)
    transaction_code = db.Column(db.String(50), nullable=True)
    check_number = db.Column(db.String(50), nullable=True)
    account_owner = db.Column(db.String(255), nullable=True)
    pending = db.Column(db.Boolean, default=False, nullable=False)
    pending_transaction_id = db.Column(db.String(255), nullable=True)
    location = db.Column(JSONType, nullable=True)
    counterparties = db.Column(JSONType, nullable=True)
    removed = db.Column(db.Boolean, default=False, nullable=False)
    # The grouping key this row belongs to: 'entity:<merchant_entity_id>' when
    # Plaid supplied an entity id, else normalize_merchant(merchant_name or
    # description). Written at upsert so the subscriptions/bills read path is an
    # indexed join instead of a per-request normalization pass. Nullable because
    # rows predating the merchant-group index have none until it is built.
    merchant_key = db.Column(db.String(255), nullable=True)
    created_at = db.Column(db.DateTime(timezone=True), default=_utcnow, nullable=False)
    updated_at = db.Column(
        db.DateTime(timezone=True), default=_utcnow, onupdate=_utcnow, nullable=False
    )

    __table_args__ = (
        db.Index('ix_transactions_date', 'date'),
        db.Index('ix_transactions_merchant_key', 'merchant_key'),
    )


class SyncLog(db.Model):
    __tablename__ = 'sync_logs'

    id = db.Column(db.Integer, primary_key=True)
    institution_id = db.Column(
        db.Integer, db.ForeignKey('institutions.id', ondelete='SET NULL'), nullable=True
    )
    started_at = db.Column(db.DateTime(timezone=True), default=_utcnow, nullable=False)
    completed_at = db.Column(db.DateTime(timezone=True), nullable=True)
    added_count = db.Column(db.Integer, default=0, nullable=False)
    removed_count = db.Column(db.Integer, default=0, nullable=False)
    error = db.Column(db.Text, nullable=True)


class DailyDigest(db.Model):
    """One row per daily digest SMS actually sent.

    Grain is (local ``sent_date``, ``recipient``): each recipient is texted at
    most once per calendar day. Written only after a successful Twilio send, so
    a failed send is retried on the next dispatch. The unique constraint is also
    the cross-process dedup backstop for the notifier's module-level lock (see
    app/notifications.py).
    """
    __tablename__ = 'daily_digests'

    id = db.Column(db.Integer, primary_key=True)
    sent_date = db.Column(db.Date, nullable=False)
    recipient = db.Column(db.String(32), nullable=False)
    sent_at = db.Column(db.DateTime(timezone=True), default=_utcnow, nullable=False)

    __table_args__ = (
        db.UniqueConstraint(
            'sent_date', 'recipient', name='uq_daily_digests_date_recipient',
        ),
    )


class MerchantGroup(db.Model):
    """One detected merchant identity — the unit /subscriptions and /bills group by.

    ``canonical_key`` is frozen at creation and is what later keys fuzzy-match
    against. It is deliberately NOT recomputed from the group's name
    distribution on each pass: a moving canonical key would make a group's
    matching behaviour depend on the order transactions happened to arrive in,
    which is the instability this index exists to remove.

    ``algo_version`` records the grouping algorithm that built the row. A
    mismatch against ``GROUPING_ALGO_VERSION`` triggers exactly one full rebuild
    (see app/merchant_groups.py), so changing the fuzzy threshold or the
    normalizer can never leave a silently stale index behind.
    """

    __tablename__ = 'merchant_groups'

    id = db.Column(db.Integer, primary_key=True)
    canonical_key = db.Column(db.String(255), nullable=False)
    algo_version = db.Column(db.Integer, nullable=False)
    # True when this group was opened from a merchant_entity_id. Two distinct
    # entity ids must never merge into one group, however alike their names
    # look: the in-memory path never compares entity groups against each other,
    # and letting the persisted path do so makes the two disagree about which
    # subscriptions exist.
    from_entity = db.Column(db.Boolean, default=False, nullable=False)
    created_at = db.Column(db.DateTime(timezone=True), default=_utcnow, nullable=False)


class MerchantGroupKey(db.Model):
    """A merchant key mapped to its group. One row per distinct key ever seen.

    Grain is the key, not the transaction: thousands of transactions share a
    key, and the read path joins transactions to groups through this table.
    """

    __tablename__ = 'merchant_group_keys'

    id = db.Column(db.Integer, primary_key=True)
    key = db.Column(db.String(255), unique=True, nullable=False)
    group_id = db.Column(
        db.Integer,
        db.ForeignKey('merchant_groups.id', ondelete='CASCADE'),
        nullable=False,
    )

    __table_args__ = (
        db.Index('ix_merchant_group_keys_group_id', 'group_id'),
    )
