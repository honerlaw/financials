"""add vested/unvested equity compensation fields to accounts

Revision ID: e9c2b7d41a58
Revises: d5a1c9e37b48
Create Date: 2026-08-23 12:00:00.000000

"""
from alembic import op
import sqlalchemy as sa


revision = 'e9c2b7d41a58'
down_revision = 'd5a1c9e37b48'
branch_labels = None
depends_on = None


def upgrade():
    op.add_column('accounts', sa.Column('vested_value', sa.Numeric(precision=12, scale=2), nullable=True))
    op.add_column('accounts', sa.Column('unvested_value', sa.Numeric(precision=12, scale=2), nullable=True))


def downgrade():
    op.drop_column('accounts', 'unvested_value')
    op.drop_column('accounts', 'vested_value')
