"""add LLM-analytical fields to transactions

Revision ID: 2a1f9c7e5d3b
Revises: 00a2889ed2af
Create Date: 2026-05-17 17:00:00.000000

"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import JSONB


revision = '2a1f9c7e5d3b'
down_revision = '00a2889ed2af'
branch_labels = None
depends_on = None


def upgrade():
    with op.batch_alter_table('transactions', schema=None) as batch_op:
        batch_op.add_column(sa.Column('authorized_date', sa.Date(), nullable=True))
        batch_op.add_column(sa.Column('original_description', sa.String(length=512), nullable=True))
        batch_op.add_column(sa.Column('merchant_entity_id', sa.String(length=255), nullable=True))
        batch_op.add_column(sa.Column('website', sa.String(length=512), nullable=True))
        batch_op.add_column(sa.Column('iso_currency_code', sa.String(length=10), nullable=True))
        batch_op.add_column(sa.Column('category_detailed', sa.String(length=255), nullable=True))
        batch_op.add_column(sa.Column('category_confidence', sa.String(length=50), nullable=True))
        batch_op.add_column(sa.Column('payment_channel', sa.String(length=50), nullable=True))
        batch_op.add_column(sa.Column('transaction_code', sa.String(length=50), nullable=True))
        batch_op.add_column(sa.Column('check_number', sa.String(length=50), nullable=True))
        batch_op.add_column(sa.Column('account_owner', sa.String(length=255), nullable=True))
        batch_op.add_column(sa.Column(
            'pending', sa.Boolean(), nullable=False, server_default=sa.false()
        ))
        batch_op.add_column(sa.Column('pending_transaction_id', sa.String(length=255), nullable=True))
        batch_op.add_column(sa.Column('location', JSONB(), nullable=True))
        batch_op.add_column(sa.Column('counterparties', JSONB(), nullable=True))

    # Drop the server_default after backfill so SQLAlchemy controls the value on insert.
    with op.batch_alter_table('transactions', schema=None) as batch_op:
        batch_op.alter_column('pending', server_default=None)


def downgrade():
    with op.batch_alter_table('transactions', schema=None) as batch_op:
        batch_op.drop_column('counterparties')
        batch_op.drop_column('location')
        batch_op.drop_column('pending_transaction_id')
        batch_op.drop_column('pending')
        batch_op.drop_column('account_owner')
        batch_op.drop_column('check_number')
        batch_op.drop_column('transaction_code')
        batch_op.drop_column('payment_channel')
        batch_op.drop_column('category_confidence')
        batch_op.drop_column('category_detailed')
        batch_op.drop_column('iso_currency_code')
        batch_op.drop_column('website')
        batch_op.drop_column('merchant_entity_id')
        batch_op.drop_column('original_description')
        batch_op.drop_column('authorized_date')
