"""add access map fields
Revision ID: 0002_access_maps
Revises: 0001_initial
Create Date: 2026-07-12
"""
from alembic import op
import sqlalchemy as sa

revision='0002_access_maps'
down_revision='0001_initial'
branch_labels=None
depends_on=None

def upgrade():
    op.add_column('surf_spots', sa.Column('access_map_asset', sa.String(255), nullable=True))
    op.add_column('surf_spots', sa.Column('access_map_id', sa.String(120), nullable=True))
    op.add_column('surf_spots', sa.Column('external_navigation_url', sa.String(500), nullable=True))
    op.add_column('surf_spots', sa.Column('access_map_status', sa.String(30), nullable=False, server_default='missing'))
    op.create_index(op.f('ix_surf_spots_access_map_id'), 'surf_spots', ['access_map_id'], unique=False)

def downgrade():
    op.drop_index(op.f('ix_surf_spots_access_map_id'), table_name='surf_spots')
    op.drop_column('surf_spots', 'access_map_status')
    op.drop_column('surf_spots', 'external_navigation_url')
    op.drop_column('surf_spots', 'access_map_id')
    op.drop_column('surf_spots', 'access_map_asset')
