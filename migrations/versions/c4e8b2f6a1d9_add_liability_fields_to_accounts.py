"""add liability fields to accounts

Revision ID: c4e8b2f6a1d9
Revises: b7f3a9c1d2e4
Create Date: 2026-07-12 12:00:00.000000

"""
from alembic import op
import sqlalchemy as sa


revision = 'c4e8b2f6a1d9'
down_revision = 'b7f3a9c1d2e4'
branch_labels = None
depends_on = None


def upgrade():
    op.add_column('accounts', sa.Column('next_payment_due_date', sa.Date(), nullable=True))
    op.add_column('accounts', sa.Column('last_statement_balance', sa.Numeric(precision=12, scale=2), nullable=True))
    op.add_column('accounts', sa.Column('minimum_payment_amount', sa.Numeric(precision=12, scale=2), nullable=True))


def downgrade():
    op.drop_column('accounts', 'minimum_payment_amount')
    op.drop_column('accounts', 'last_statement_balance')
    op.drop_column('accounts', 'next_payment_due_date')
