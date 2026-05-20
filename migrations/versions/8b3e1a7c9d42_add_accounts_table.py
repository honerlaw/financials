"""add accounts table

Revision ID: 8b3e1a7c9d42
Revises: 2a1f9c7e5d3b
Create Date: 2026-05-20 12:00:00.000000

"""
from alembic import op
import sqlalchemy as sa


revision = '8b3e1a7c9d42'
down_revision = '2a1f9c7e5d3b'
branch_labels = None
depends_on = None


def upgrade():
    op.create_table(
        'accounts',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('institution_id', sa.Integer(), nullable=False),
        sa.Column('plaid_account_id', sa.String(length=255), nullable=False),
        sa.Column('name', sa.String(length=255), nullable=False),
        sa.Column('official_name', sa.String(length=255), nullable=True),
        sa.Column('mask', sa.String(length=8), nullable=True),
        sa.Column('type', sa.String(length=50), nullable=True),
        sa.Column('subtype', sa.String(length=50), nullable=True),
        sa.Column('current_balance', sa.Numeric(precision=12, scale=2), nullable=True),
        sa.Column('available_balance', sa.Numeric(precision=12, scale=2), nullable=True),
        sa.Column('iso_currency_code', sa.String(length=10), nullable=True),
        sa.Column('last_synced_at', sa.DateTime(timezone=True), nullable=True),
        sa.Column('created_at', sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(['institution_id'], ['institutions.id'], ondelete='CASCADE'),
        sa.PrimaryKeyConstraint('id'),
        sa.UniqueConstraint('plaid_account_id'),
    )


def downgrade():
    op.drop_table('accounts')
