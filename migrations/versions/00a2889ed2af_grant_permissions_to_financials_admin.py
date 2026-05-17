"""grant permissions to financials_admin

Revision ID: 00a2889ed2af
Revises: 4137df7397b7
Create Date: 2026-05-17 16:20:00.000000

"""
from alembic import op


revision = '00a2889ed2af'
down_revision = '4137df7397b7'
branch_labels = None
depends_on = None


GRANTEE = 'financials_admin'


def upgrade():
    op.execute(f'GRANT USAGE ON SCHEMA public TO "{GRANTEE}"')
    op.execute(
        f'GRANT SELECT, INSERT, UPDATE, DELETE ON ALL TABLES IN SCHEMA public TO "{GRANTEE}"'
    )
    op.execute(
        f'GRANT USAGE, SELECT ON ALL SEQUENCES IN SCHEMA public TO "{GRANTEE}"'
    )
    op.execute(
        f'ALTER DEFAULT PRIVILEGES IN SCHEMA public '
        f'GRANT SELECT, INSERT, UPDATE, DELETE ON TABLES TO "{GRANTEE}"'
    )
    op.execute(
        f'ALTER DEFAULT PRIVILEGES IN SCHEMA public '
        f'GRANT USAGE, SELECT ON SEQUENCES TO "{GRANTEE}"'
    )


def downgrade():
    op.execute(
        f'ALTER DEFAULT PRIVILEGES IN SCHEMA public '
        f'REVOKE SELECT, INSERT, UPDATE, DELETE ON TABLES FROM "{GRANTEE}"'
    )
    op.execute(
        f'ALTER DEFAULT PRIVILEGES IN SCHEMA public '
        f'REVOKE USAGE, SELECT ON SEQUENCES FROM "{GRANTEE}"'
    )
    op.execute(
        f'REVOKE SELECT, INSERT, UPDATE, DELETE ON ALL TABLES IN SCHEMA public FROM "{GRANTEE}"'
    )
    op.execute(
        f'REVOKE USAGE, SELECT ON ALL SEQUENCES IN SCHEMA public FROM "{GRANTEE}"'
    )
    op.execute(f'REVOKE USAGE ON SCHEMA public FROM "{GRANTEE}"')
