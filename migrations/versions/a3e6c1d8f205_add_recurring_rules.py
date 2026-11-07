"""add recurring_rules (user corrections to /recurring)

Revision ID: a3e6c1d8f205
Revises: f2d7a4b91c63
Create Date: 2026-11-07 12:00:00.000000

A new, empty table — no backfill. Rules are applied per request over the
detection rows (app/recurring_rules.py), so dropping the table on downgrade
returns /recurring to pure automatic detection.
"""
from alembic import op
import sqlalchemy as sa


revision = 'a3e6c1d8f205'
down_revision = 'f2d7a4b91c63'
branch_labels = None
depends_on = None


def upgrade():
    op.create_table(
        'recurring_rules',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('label', sa.String(length=255), nullable=False),
        sa.Column('pattern', sa.String(length=255), nullable=False),
        sa.Column('direction', sa.String(length=10), nullable=False),
        sa.Column('amount_min', sa.Numeric(precision=10, scale=2), nullable=True),
        sa.Column('amount_max', sa.Numeric(precision=10, scale=2), nullable=True),
        sa.Column('action', sa.String(length=20), nullable=False),
        sa.Column('created_at', sa.DateTime(timezone=True), nullable=False),
        sa.PrimaryKeyConstraint('id'),
    )


def downgrade():
    op.drop_table('recurring_rules')
