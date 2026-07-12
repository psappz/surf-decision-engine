"""user favorite surf spots
Revision ID: 0005_user_favs
Revises: 0004_spot_admin_media
Create Date: 2026-07-12
"""
from alembic import op
import sqlalchemy as sa

revision = '0005_user_favs'
down_revision = '0004_spot_admin_media'
branch_labels = None
depends_on = None


def upgrade():
    op.create_table(
        'user_favorite_spots',
        sa.Column('id', sa.Integer(), primary_key=True),
        sa.Column('user_id', sa.Integer(), sa.ForeignKey('users.id'), nullable=False),
        sa.Column('spot_id', sa.Integer(), sa.ForeignKey('surf_spots.id'), nullable=False),
        sa.Column('created_at', sa.DateTime(timezone=True), nullable=False),
        sa.UniqueConstraint('user_id', 'spot_id', name='uq_user_favorite_spot'),
    )
    op.create_index('ix_user_favorite_spots_user_id', 'user_favorite_spots', ['user_id'])
    op.create_index('ix_user_favorite_spots_spot_id', 'user_favorite_spots', ['spot_id'])
    op.create_index('ix_user_favorite_spots_created_at', 'user_favorite_spots', ['created_at'])


def downgrade():
    op.drop_index('ix_user_favorite_spots_created_at', table_name='user_favorite_spots')
    op.drop_index('ix_user_favorite_spots_spot_id', table_name='user_favorite_spots')
    op.drop_index('ix_user_favorite_spots_user_id', table_name='user_favorite_spots')
    op.drop_table('user_favorite_spots')
