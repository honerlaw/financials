"""add essential_marks (streams the user marked essential on /recurring)

Revision ID: b8d4e2f7a9c1
Revises: a3e6c1d8f205
Create Date: 2026-11-07 18:00:00.000000

A new, empty table — no backfill. No GRANT is needed: 00a2889ed2af set
default privileges for financials_admin on new tables. Dropping the table on
downgrade leaves every recurring expense unmarked; detection is unaffected.
"""
from alembic import op
import sqlalchemy as sa


revision = 'b8d4e2f7a9c1'
down_revision = 'a3e6c1d8f205'
branch_labels = None
depends_on = None


def upgrade():
    op.create_table(
        'essential_marks',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('stream_key', sa.String(length=255), nullable=False),
        sa.Column('created_at', sa.DateTime(timezone=True), nullable=False),
        sa.PrimaryKeyConstraint('id'),
        sa.UniqueConstraint('stream_key'),
    )


def downgrade():
    op.drop_table('essential_marks')
