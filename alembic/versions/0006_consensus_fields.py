"""add typed consensus forecast fields
Revision ID: 0006_consensus_fields
Revises: 0005_forecast_ledger
Create Date: 2026-07-13
"""
from alembic import op
import sqlalchemy as sa

revision = '0006_consensus_fields'
down_revision = '0005_forecast_ledger'
branch_labels = None
depends_on = None

COLUMNS = (
    'swell_wave_height',
    'swell_wave_direction',
    'swell_wave_period',
    'wind_wave_height',
    'wind_wave_direction',
    'wind_wave_period',
    'wind_gust',
    'water_temperature',
    'current_speed',
    'current_direction',
)


def upgrade():
    for name in COLUMNS:
        op.add_column('consensus_forecast_points', sa.Column(name, sa.Float(), nullable=True))


def downgrade():
    for name in reversed(COLUMNS):
        op.drop_column('consensus_forecast_points', name)
