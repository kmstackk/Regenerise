"""Re-add smart_wakeup_window to alarms

smart_wakeup_window was dropped in migration 5c2c248b5c58 but is required
by the alarm algorithm to determine the smart wake-up window in minutes
before the target alarm time. Default is 20 minutes.

Revision ID: a1b2c3d4e5f6
Revises: 5c2c248b5c58
Create Date: 2026-04-25 12:00:00.000000
"""
from alembic import op
import sqlalchemy as sa

revision = 'a1b2c3d4e5f6'
down_revision = '5c2c248b5c58'
branch_labels = None
depends_on = None


def upgrade():
    with op.batch_alter_table('alarms', schema=None) as batch_op:
        batch_op.add_column(
            sa.Column('smart_wakeup_window', sa.Integer(), nullable=True, server_default='20')
        )


def downgrade():
    with op.batch_alter_table('alarms', schema=None) as batch_op:
        batch_op.drop_column('smart_wakeup_window')
