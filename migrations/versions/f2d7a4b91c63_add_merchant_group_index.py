"""add merchant group index (merchant_key + merchant_groups + merchant_group_keys)

Revision ID: f2d7a4b91c63
Revises: e9c2b7d41a58
Create Date: 2026-08-24 12:00:00.000000

Schema only — no data backfill. `normalize_merchant` is a Python function and
cannot run inside a SQL migration, so `transactions.merchant_key` starts NULL
for every existing row and the index is built lazily: the first /subscriptions
or /bills load with an incomplete index computes the grouping in memory (the
pre-existing pure-function path) and persists the result. That keeps deploy
cheap and leaves no window where the pages render empty.
"""
from alembic import op
import sqlalchemy as sa


revision = 'f2d7a4b91c63'
down_revision = 'e9c2b7d41a58'
branch_labels = None
depends_on = None


def upgrade():
    op.add_column('transactions', sa.Column('merchant_key', sa.String(length=255), nullable=True))
    op.create_index('ix_transactions_merchant_key', 'transactions', ['merchant_key'])

    op.create_table(
        'merchant_groups',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('canonical_key', sa.String(length=255), nullable=False),
        sa.Column('algo_version', sa.Integer(), nullable=False),
        sa.Column('created_at', sa.DateTime(timezone=True), nullable=False),
        sa.PrimaryKeyConstraint('id'),
    )

    op.create_table(
        'merchant_group_keys',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('key', sa.String(length=255), nullable=False),
        sa.Column('group_id', sa.Integer(), nullable=False),
        sa.ForeignKeyConstraint(['group_id'], ['merchant_groups.id'], ondelete='CASCADE'),
        sa.PrimaryKeyConstraint('id'),
        sa.UniqueConstraint('key'),
    )
    op.create_index('ix_merchant_group_keys_group_id', 'merchant_group_keys', ['group_id'])


def downgrade():
    op.drop_index('ix_merchant_group_keys_group_id', table_name='merchant_group_keys')
    op.drop_table('merchant_group_keys')
    op.drop_table('merchant_groups')
    op.drop_index('ix_transactions_merchant_key', table_name='transactions')
    op.drop_column('transactions', 'merchant_key')
