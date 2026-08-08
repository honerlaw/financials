"""replace budget_alerts with daily_digests

The 50/75/100% threshold alert is retired in favour of one daily digest per
recipient (see .minerva/work/016-daily-balance-digest). `budget_alerts` was a
send-log for that retired feature with no reader anywhere in the app, so it is
dropped rather than left behind; `downgrade` recreates it (rows are not
recoverable, by design).

Revision ID: d5a1c9e37b48
Revises: c4e8b2f6a1d9
"""
from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = 'd5a1c9e37b48'
down_revision = 'c4e8b2f6a1d9'
branch_labels = None
depends_on = None


def upgrade():
    op.create_table(
        'daily_digests',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('sent_date', sa.Date(), nullable=False),
        sa.Column('recipient', sa.String(length=32), nullable=False),
        sa.Column('sent_at', sa.DateTime(timezone=True), nullable=False),
        sa.PrimaryKeyConstraint('id'),
        sa.UniqueConstraint('sent_date', 'recipient',
                            name='uq_daily_digests_date_recipient'),
    )
    op.drop_table('budget_alerts')


def downgrade():
    op.create_table(
        'budget_alerts',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('week_start', sa.Date(), nullable=False),
        sa.Column('threshold', sa.Integer(), nullable=False),
        sa.Column('recipient', sa.String(length=32), nullable=False),
        sa.Column('sent_at', sa.DateTime(timezone=True), nullable=False),
        sa.PrimaryKeyConstraint('id'),
        sa.UniqueConstraint('week_start', 'threshold', 'recipient',
                            name='uq_budget_alerts_week_threshold_recipient'),
    )
    op.drop_table('daily_digests')
