"""add copernicus publication and job tables
Revision ID: 0003_copernicus_publications
Revises: 0002_access_maps
Create Date: 2026-07-12
"""
from alembic import op
import sqlalchemy as sa

revision='0003_copernicus_publications'
down_revision='0002_access_maps'
branch_labels=None
depends_on=None


def upgrade():
    op.create_table(
        'copernicus_publications',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('provider', sa.String(length=100), nullable=False),
        sa.Column('product_id', sa.String(length=160), nullable=False),
        sa.Column('dataset_id', sa.String(length=220), nullable=False),
        sa.Column('publication_identity', sa.String(length=500), nullable=False),
        sa.Column('model_cycle_time', sa.DateTime(timezone=True), nullable=True),
        sa.Column('latest_available_forecast_time', sa.DateTime(timezone=True), nullable=True),
        sa.Column('detected_at', sa.DateTime(timezone=True), nullable=True),
        sa.Column('ingestion_started_at', sa.DateTime(timezone=True), nullable=True),
        sa.Column('ingestion_completed_at', sa.DateTime(timezone=True), nullable=True),
        sa.Column('status', sa.String(length=40), nullable=False),
        sa.Column('error', sa.Text(), nullable=True),
        sa.Column('download_size', sa.BigInteger(), nullable=True),
        sa.Column('checksum', sa.String(length=128), nullable=True),
        sa.Column('raw_file_path', sa.String(length=800), nullable=True),
        sa.Column('metadata_json', sa.JSON(), nullable=True),
        sa.Column('created_at', sa.DateTime(timezone=True), nullable=False),
        sa.Column('updated_at', sa.DateTime(timezone=True), nullable=False),
        sa.PrimaryKeyConstraint('id'),
        sa.UniqueConstraint('provider', 'dataset_id', 'publication_identity', name='uq_copernicus_publication_identity'),
    )
    op.create_index(op.f('ix_copernicus_publications_provider'), 'copernicus_publications', ['provider'], unique=False)
    op.create_index(op.f('ix_copernicus_publications_dataset_id'), 'copernicus_publications', ['dataset_id'], unique=False)
    op.create_index(op.f('ix_copernicus_publications_publication_identity'), 'copernicus_publications', ['publication_identity'], unique=False)
    op.create_index(op.f('ix_copernicus_publications_status'), 'copernicus_publications', ['status'], unique=False)
    op.create_table(
        'copernicus_ingestion_jobs',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('publication_id', sa.Integer(), nullable=False),
        sa.Column('status', sa.String(length=40), nullable=False),
        sa.Column('lease_token', sa.String(length=128), nullable=True),
        sa.Column('lease_until', sa.DateTime(timezone=True), nullable=True),
        sa.Column('attempts', sa.Integer(), nullable=False),
        sa.Column('last_error', sa.Text(), nullable=True),
        sa.Column('created_at', sa.DateTime(timezone=True), nullable=False),
        sa.Column('updated_at', sa.DateTime(timezone=True), nullable=False),
        sa.Column('started_at', sa.DateTime(timezone=True), nullable=True),
        sa.Column('completed_at', sa.DateTime(timezone=True), nullable=True),
        sa.ForeignKeyConstraint(['publication_id'], ['copernicus_publications.id'], ),
        sa.PrimaryKeyConstraint('id')
    )
    op.create_index(op.f('ix_copernicus_ingestion_jobs_publication_id'), 'copernicus_ingestion_jobs', ['publication_id'], unique=False)
    op.create_index(op.f('ix_copernicus_ingestion_jobs_status'), 'copernicus_ingestion_jobs', ['status'], unique=False)


def downgrade():
    op.drop_index(op.f('ix_copernicus_ingestion_jobs_status'), table_name='copernicus_ingestion_jobs')
    op.drop_index(op.f('ix_copernicus_ingestion_jobs_publication_id'), table_name='copernicus_ingestion_jobs')
    op.drop_table('copernicus_ingestion_jobs')
    op.drop_index(op.f('ix_copernicus_publications_status'), table_name='copernicus_publications')
    op.drop_index(op.f('ix_copernicus_publications_publication_identity'), table_name='copernicus_publications')
    op.drop_index(op.f('ix_copernicus_publications_dataset_id'), table_name='copernicus_publications')
    op.drop_index(op.f('ix_copernicus_publications_provider'), table_name='copernicus_publications')
    op.drop_table('copernicus_publications')
