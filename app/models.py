from datetime import datetime, timezone
from app import db


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


class Transaction(db.Model):
    __tablename__ = 'transactions'

    id = db.Column(db.Integer, primary_key=True)
    plaid_transaction_id = db.Column(db.String(255), unique=True, nullable=False)
    institution_id = db.Column(
        db.Integer, db.ForeignKey('institutions.id', ondelete='CASCADE'), nullable=False
    )
    account_id = db.Column(db.String(255), nullable=False)
    date = db.Column(db.Date, nullable=False)
    description = db.Column(db.String(512), nullable=False)
    merchant_name = db.Column(db.String(255), nullable=True)
    amount = db.Column(db.Numeric(10, 2), nullable=False)
    category = db.Column(db.String(255), nullable=True)
    removed = db.Column(db.Boolean, default=False, nullable=False)
    created_at = db.Column(db.DateTime(timezone=True), default=_utcnow, nullable=False)
    updated_at = db.Column(
        db.DateTime(timezone=True), default=_utcnow, onupdate=_utcnow, nullable=False
    )

    __table_args__ = (
        db.Index('ix_transactions_date', 'date'),
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
