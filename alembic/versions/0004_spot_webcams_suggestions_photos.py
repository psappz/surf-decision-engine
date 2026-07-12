"""spot webcams suggestions photos
Revision ID: 0004_spot_admin_media
Revises: 0003_copernicus_publications
Create Date: 2026-07-12
"""
from alembic import op
import sqlalchemy as sa

revision = '0004_spot_admin_media'
down_revision='0003_copernicus_publications'
branch_labels=None
depends_on=None

def upgrade():
    op.create_table('spot_webcams',
        sa.Column('id', sa.Integer, primary_key=True),
        sa.Column('spot_id', sa.Integer, sa.ForeignKey('surf_spots.id'), nullable=False),
        sa.Column('title', sa.String(180), nullable=False),
        sa.Column('operator_name', sa.String(180), nullable=False),
        sa.Column('url', sa.String(1000), nullable=False),
        sa.Column('description', sa.Text, nullable=True),
        sa.Column('is_active', sa.Boolean, nullable=False, server_default=sa.true()),
        sa.Column('sort_order', sa.Integer, nullable=False, server_default='0'),
        sa.Column('created_at', sa.DateTime(timezone=True), nullable=False),
        sa.Column('updated_at', sa.DateTime(timezone=True), nullable=False),
        sa.Column('created_by_user_id', sa.Integer, sa.ForeignKey('users.id'), nullable=True),
        sa.Column('approved_source_type', sa.String(40), nullable=False, server_default='operator'))
    op.create_index('ix_spot_webcams_spot_id', 'spot_webcams', ['spot_id'])
    op.create_index('ix_spot_webcams_is_active', 'spot_webcams', ['is_active'])
    op.create_index('ix_spot_webcams_sort_order', 'spot_webcams', ['sort_order'])

    op.create_table('webcam_suggestions',
        sa.Column('id', sa.Integer, primary_key=True),
        sa.Column('spot_id', sa.Integer, sa.ForeignKey('surf_spots.id'), nullable=False),
        sa.Column('submitted_by_user_id', sa.Integer, sa.ForeignKey('users.id'), nullable=False),
        sa.Column('suggested_url', sa.String(1000), nullable=False),
        sa.Column('suggested_title', sa.String(180), nullable=False),
        sa.Column('suggested_operator_name', sa.String(180), nullable=False),
        sa.Column('submitter_note', sa.Text, nullable=True),
        sa.Column('status', sa.String(30), nullable=False, server_default='pending'),
        sa.Column('moderator_note', sa.Text, nullable=True),
        sa.Column('reviewed_by_user_id', sa.Integer, sa.ForeignKey('users.id'), nullable=True),
        sa.Column('submitted_at', sa.DateTime(timezone=True), nullable=False),
        sa.Column('reviewed_at', sa.DateTime(timezone=True), nullable=True),
        sa.Column('approved_webcam_id', sa.Integer, sa.ForeignKey('spot_webcams.id'), nullable=True),
        sa.UniqueConstraint('spot_id','suggested_url','status', name='uq_webcam_suggestion_spot_url_status'))
    op.create_index('ix_webcam_suggestions_spot_id', 'webcam_suggestions', ['spot_id'])
    op.create_index('ix_webcam_suggestions_submitted_by_user_id', 'webcam_suggestions', ['submitted_by_user_id'])
    op.create_index('ix_webcam_suggestions_status', 'webcam_suggestions', ['status'])
    op.create_index('ix_webcam_suggestions_submitted_at', 'webcam_suggestions', ['submitted_at'])

    op.create_table('spot_photos',
        sa.Column('id', sa.Integer, primary_key=True),
        sa.Column('spot_id', sa.Integer, sa.ForeignKey('surf_spots.id'), nullable=False),
        sa.Column('uploaded_by_user_id', sa.Integer, sa.ForeignKey('users.id'), nullable=False),
        sa.Column('display_path', sa.String(800), nullable=False),
        sa.Column('thumbnail_path', sa.String(800), nullable=False),
        sa.Column('original_filename', sa.String(255), nullable=True),
        sa.Column('stored_mime_type', sa.String(80), nullable=False),
        sa.Column('width', sa.Integer, nullable=False),
        sa.Column('height', sa.Integer, nullable=False),
        sa.Column('file_size', sa.Integer, nullable=False),
        sa.Column('caption', sa.String(500), nullable=True),
        sa.Column('status', sa.String(30), nullable=False, server_default='active'),
        sa.Column('created_at', sa.DateTime(timezone=True), nullable=False),
        sa.Column('updated_at', sa.DateTime(timezone=True), nullable=False))
    op.create_index('ix_spot_photos_spot_id', 'spot_photos', ['spot_id'])
    op.create_index('ix_spot_photos_uploaded_by_user_id', 'spot_photos', ['uploaded_by_user_id'])
    op.create_index('ix_spot_photos_status', 'spot_photos', ['status'])

    # Deprecated seeded/aggregator webcam_url values are intentionally nulled instead
    # of migrated into approved operator-owned webcam records.
    op.execute("UPDATE surf_spots SET webcam_url = NULL WHERE webcam_url IS NOT NULL")

def downgrade():
    op.drop_table('spot_photos')
    op.drop_table('webcam_suggestions')
    op.drop_table('spot_webcams')
