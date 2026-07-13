"""append only forecast ledger
Revision ID: 0005_forecast_ledger
Revises: 0005_user_favs
Create Date: 2026-07-13
"""
from alembic import op
import sqlalchemy as sa

revision = '0005_forecast_ledger'
down_revision = '0005_user_favs'
branch_labels = None
depends_on = None

_metadata = sa.MetaData()

# Existing tables referenced by restrictive ledger foreign keys. They are
# placeholders for SQL compilation only; this migration does not create them.
sa.Table('provider_fetches', _metadata, sa.Column('id', sa.Integer(), primary_key=True))
sa.Table('surf_spots', _metadata, sa.Column('id', sa.Integer(), primary_key=True))

provider_publications = sa.Table(
    'provider_publications', _metadata,
    sa.Column('id', sa.Integer(), primary_key=True),
    sa.Column('provider_name', sa.String(100), nullable=False),
    sa.Column('product_id', sa.String(200), nullable=True),
    sa.Column('dataset_id', sa.String(220), nullable=False, server_default=''),
    sa.Column('publication_identity', sa.String(500), nullable=False),
    sa.Column('model_cycle_at', sa.DateTime(timezone=True), nullable=True),
    sa.Column('source_updated_at', sa.DateTime(timezone=True), nullable=True),
    sa.Column('latest_valid_at', sa.DateTime(timezone=True), nullable=True),
    sa.Column('detected_at', sa.DateTime(timezone=True), nullable=False),
    sa.Column('status', sa.String(40), nullable=False),
    sa.Column('metadata_json', sa.JSON(), nullable=True),
    sa.Column('created_at', sa.DateTime(timezone=True), nullable=False),
    sa.Column('updated_at', sa.DateTime(timezone=True), nullable=False),
    sa.UniqueConstraint('provider_name', 'dataset_id', 'publication_identity', name='uq_provider_publication_identity'),
    sa.Index('ix_provider_publications_provider_name', 'provider_name'),
    sa.Index('ix_provider_publications_publication_identity', 'publication_identity'),
    sa.Index('ix_provider_publications_model_cycle_at', 'model_cycle_at'),
    sa.Index('ix_provider_publications_status', 'status'),
    sa.Index('ix_provider_publications_detected_at', 'detected_at'),
)

forecast_runs = sa.Table(
    'forecast_runs', _metadata,
    sa.Column('id', sa.Integer(), primary_key=True),
    sa.Column('provider_name', sa.String(100), nullable=False),
    sa.Column('publication_id', sa.Integer(), sa.ForeignKey('provider_publications.id', ondelete='RESTRICT'), nullable=False),
    sa.Column('fetch_id', sa.Integer(), sa.ForeignKey('provider_fetches.id', ondelete='RESTRICT'), nullable=False),
    sa.Column('issued_at', sa.DateTime(timezone=True), nullable=False),
    sa.Column('fetched_at', sa.DateTime(timezone=True), nullable=False),
    sa.Column('normalized_at', sa.DateTime(timezone=True), nullable=False),
    sa.Column('geographic_bounds_json', sa.JSON(), nullable=True),
    sa.Column('temporal_bounds_json', sa.JSON(), nullable=True),
    sa.Column('schema_version', sa.String(80), nullable=False),
    sa.Column('normalizer_version', sa.String(120), nullable=False),
    sa.Column('normalizer_configuration_hash', sa.String(128), nullable=False),
    sa.Column('status', sa.String(40), nullable=False),
    sa.Column('error_message', sa.Text(), nullable=True),
    sa.Column('created_at', sa.DateTime(timezone=True), nullable=False),
    sa.UniqueConstraint('fetch_id', 'normalizer_version', 'normalizer_configuration_hash', name='uq_forecast_run_fetch_normalizer_config'),
    sa.Index('ix_forecast_runs_provider_name', 'provider_name'),
    sa.Index('ix_forecast_runs_publication_id', 'publication_id'),
    sa.Index('ix_forecast_runs_fetch_id', 'fetch_id'),
    sa.Index('ix_forecast_runs_issued_at', 'issued_at'),
    sa.Index('ix_forecast_runs_status', 'status'),
)

provider_forecast_points = sa.Table(
    'provider_forecast_points', _metadata,
    sa.Column('id', sa.Integer(), primary_key=True),
    sa.Column('forecast_run_id', sa.Integer(), sa.ForeignKey('forecast_runs.id', ondelete='RESTRICT'), nullable=False),
    sa.Column('spot_id', sa.Integer(), sa.ForeignKey('surf_spots.id', ondelete='RESTRICT'), nullable=False),
    sa.Column('sample_point_id', sa.String(120), nullable=False, server_default=''),
    sa.Column('valid_at', sa.DateTime(timezone=True), nullable=False),
    sa.Column('wave_height', sa.Float(), nullable=True),
    sa.Column('wave_direction', sa.Float(), nullable=True),
    sa.Column('wave_period', sa.Float(), nullable=True),
    sa.Column('swell_wave_height', sa.Float(), nullable=True),
    sa.Column('swell_wave_direction', sa.Float(), nullable=True),
    sa.Column('swell_wave_period', sa.Float(), nullable=True),
    sa.Column('wind_wave_height', sa.Float(), nullable=True),
    sa.Column('wind_wave_direction', sa.Float(), nullable=True),
    sa.Column('wind_wave_period', sa.Float(), nullable=True),
    sa.Column('wind_speed', sa.Float(), nullable=True),
    sa.Column('wind_direction', sa.Float(), nullable=True),
    sa.Column('wind_gust', sa.Float(), nullable=True),
    sa.Column('water_temperature', sa.Float(), nullable=True),
    sa.Column('current_speed', sa.Float(), nullable=True),
    sa.Column('current_direction', sa.Float(), nullable=True),
    sa.Column('tide_height', sa.Float(), nullable=True),
    sa.Column('tide_state', sa.String(40), nullable=True),
    sa.Column('raw_values_json', sa.JSON(), nullable=True),
    sa.Column('quality_flags_json', sa.JSON(), nullable=True),
    sa.Column('created_at', sa.DateTime(timezone=True), nullable=False),
    sa.UniqueConstraint('forecast_run_id', 'spot_id', 'sample_point_id', 'valid_at', name='uq_provider_point_run_spot_sample_valid'),
    sa.CheckConstraint('wave_height IS NULL OR wave_height >= 0', name='ck_provider_point_wave_height_nonnegative'),
    sa.CheckConstraint('wave_period IS NULL OR wave_period >= 0', name='ck_provider_point_wave_period_nonnegative'),
    sa.CheckConstraint('wind_speed IS NULL OR wind_speed >= 0', name='ck_provider_point_wind_speed_nonnegative'),
    sa.Index('ix_provider_forecast_points_forecast_run_id', 'forecast_run_id'),
    sa.Index('ix_provider_forecast_points_spot_id', 'spot_id'),
    sa.Index('ix_provider_forecast_points_valid_at', 'valid_at'),
)

consensus_runs = sa.Table(
    'consensus_runs', _metadata,
    sa.Column('id', sa.Integer(), primary_key=True),
    sa.Column('calculated_at', sa.DateTime(timezone=True), nullable=False),
    sa.Column('forecast_cutoff_at', sa.DateTime(timezone=True), nullable=False),
    sa.Column('consensus_engine_version', sa.String(120), nullable=False),
    sa.Column('configuration_hash', sa.String(128), nullable=False),
    sa.Column('status', sa.String(40), nullable=False),
    sa.Column('error_message', sa.Text(), nullable=True),
    sa.Column('metadata_json', sa.JSON(), nullable=True),
    sa.Column('created_at', sa.DateTime(timezone=True), nullable=False),
)

consensus_forecast_points = sa.Table(
    'consensus_forecast_points', _metadata,
    sa.Column('id', sa.Integer(), primary_key=True),
    sa.Column('consensus_run_id', sa.Integer(), sa.ForeignKey('consensus_runs.id', ondelete='RESTRICT'), nullable=False),
    sa.Column('spot_id', sa.Integer(), sa.ForeignKey('surf_spots.id', ondelete='RESTRICT'), nullable=False),
    sa.Column('valid_at', sa.DateTime(timezone=True), nullable=False),
    sa.Column('wave_height', sa.Float(), nullable=True),
    sa.Column('wave_direction', sa.Float(), nullable=True),
    sa.Column('wave_period', sa.Float(), nullable=True),
    sa.Column('wind_speed', sa.Float(), nullable=True),
    sa.Column('wind_direction', sa.Float(), nullable=True),
    sa.Column('tide_height', sa.Float(), nullable=True),
    sa.Column('provider_count', sa.Integer(), nullable=False, server_default='0'),
    sa.Column('provider_ids_json', sa.JSON(), nullable=True),
    sa.Column('agreement_score', sa.Float(), nullable=True),
    sa.Column('freshness_score', sa.Float(), nullable=True),
    sa.Column('completeness_score', sa.Float(), nullable=True),
    sa.Column('confidence_input_score', sa.Float(), nullable=True),
    sa.Column('calculation_details_json', sa.JSON(), nullable=True),
    sa.Column('created_at', sa.DateTime(timezone=True), nullable=False),
    sa.UniqueConstraint('consensus_run_id', 'spot_id', 'valid_at', name='uq_consensus_point_run_spot_valid'),
    sa.CheckConstraint('provider_count >= 0', name='ck_consensus_point_provider_count_nonnegative'),
)

spot_assessment_runs = sa.Table(
    'spot_assessment_runs', _metadata,
    sa.Column('id', sa.Integer(), primary_key=True),
    sa.Column('consensus_run_id', sa.Integer(), sa.ForeignKey('consensus_runs.id', ondelete='RESTRICT'), nullable=False),
    sa.Column('calculated_at', sa.DateTime(timezone=True), nullable=False),
    sa.Column('spot_rules_version', sa.String(120), nullable=False),
    sa.Column('spot_rules_hash', sa.String(128), nullable=False),
    sa.Column('spot_intelligence_engine_version', sa.String(120), nullable=False),
    sa.Column('configuration_hash', sa.String(128), nullable=False),
    sa.Column('status', sa.String(40), nullable=False),
    sa.Column('error_message', sa.Text(), nullable=True),
    sa.Column('metadata_json', sa.JSON(), nullable=True),
    sa.Column('created_at', sa.DateTime(timezone=True), nullable=False),
    sa.UniqueConstraint('consensus_run_id', 'spot_rules_hash', 'spot_intelligence_engine_version', 'configuration_hash', name='uq_assessment_run_consensus_rules_engine'),
)

spot_assessment_points = sa.Table(
    'spot_assessment_points', _metadata,
    sa.Column('id', sa.Integer(), primary_key=True),
    sa.Column('assessment_run_id', sa.Integer(), sa.ForeignKey('spot_assessment_runs.id', ondelete='RESTRICT'), nullable=False),
    sa.Column('spot_id', sa.Integer(), sa.ForeignKey('surf_spots.id', ondelete='RESTRICT'), nullable=False),
    sa.Column('valid_at', sa.DateTime(timezone=True), nullable=False),
    sa.Column('swell_direction_fit', sa.Float(), nullable=True),
    sa.Column('swell_height_fit', sa.Float(), nullable=True),
    sa.Column('period_fit', sa.Float(), nullable=True),
    sa.Column('wind_direction_fit', sa.Float(), nullable=True),
    sa.Column('wind_speed_fit', sa.Float(), nullable=True),
    sa.Column('tide_fit', sa.Float(), nullable=True),
    sa.Column('exposure_adjustment', sa.Float(), nullable=True),
    sa.Column('shelter_adjustment', sa.Float(), nullable=True),
    sa.Column('breaking_wave_min', sa.Float(), nullable=True),
    sa.Column('breaking_wave_max', sa.Float(), nullable=True),
    sa.Column('hazard_flags_json', sa.JSON(), nullable=True),
    sa.Column('uncertainty_factors_json', sa.JSON(), nullable=True),
    sa.Column('factor_details_json', sa.JSON(), nullable=True),
    sa.Column('created_at', sa.DateTime(timezone=True), nullable=False),
    sa.UniqueConstraint('assessment_run_id', 'spot_id', 'valid_at', name='uq_assessment_point_run_spot_valid'),
    sa.CheckConstraint('breaking_wave_min IS NULL OR breaking_wave_min >= 0', name='ck_assessment_breaking_min_nonnegative'),
    sa.CheckConstraint('breaking_wave_max IS NULL OR breaking_wave_min IS NULL OR breaking_wave_max >= breaking_wave_min', name='ck_assessment_breaking_max_gte_min'),
)

spot_score_runs = sa.Table(
    'spot_score_runs', _metadata,
    sa.Column('id', sa.Integer(), primary_key=True),
    sa.Column('assessment_run_id', sa.Integer(), sa.ForeignKey('spot_assessment_runs.id', ondelete='RESTRICT'), nullable=False),
    sa.Column('calculated_at', sa.DateTime(timezone=True), nullable=False),
    sa.Column('scoring_engine_version', sa.String(120), nullable=False),
    sa.Column('scoring_configuration_hash', sa.String(128), nullable=False),
    sa.Column('surfer_profile_version', sa.String(120), nullable=False),
    sa.Column('surfer_profile_hash', sa.String(128), nullable=False),
    sa.Column('status', sa.String(40), nullable=False),
    sa.Column('error_message', sa.Text(), nullable=True),
    sa.Column('metadata_json', sa.JSON(), nullable=True),
    sa.Column('created_at', sa.DateTime(timezone=True), nullable=False),
    sa.UniqueConstraint('assessment_run_id', 'scoring_engine_version', 'scoring_configuration_hash', 'surfer_profile_version', 'surfer_profile_hash', name='uq_score_run_assessment_engine_config_profile'),
)

spot_score_snapshots = sa.Table(
    'spot_score_snapshots', _metadata,
    sa.Column('id', sa.Integer(), primary_key=True),
    sa.Column('score_run_id', sa.Integer(), sa.ForeignKey('spot_score_runs.id', ondelete='RESTRICT'), nullable=False),
    sa.Column('spot_id', sa.Integer(), sa.ForeignKey('surf_spots.id', ondelete='RESTRICT'), nullable=False),
    sa.Column('valid_at', sa.DateTime(timezone=True), nullable=False),
    sa.Column('total_score', sa.Float(), nullable=False),
    sa.Column('condition_classification', sa.String(80), nullable=False),
    sa.Column('swell_direction_score', sa.Float(), nullable=True),
    sa.Column('swell_height_score', sa.Float(), nullable=True),
    sa.Column('period_score', sa.Float(), nullable=True),
    sa.Column('wind_direction_score', sa.Float(), nullable=True),
    sa.Column('wind_speed_score', sa.Float(), nullable=True),
    sa.Column('tide_score', sa.Float(), nullable=True),
    sa.Column('safety_score', sa.Float(), nullable=True),
    sa.Column('penalty_total', sa.Float(), nullable=True),
    sa.Column('penalties_json', sa.JSON(), nullable=True),
    sa.Column('positive_factors_json', sa.JSON(), nullable=True),
    sa.Column('negative_factors_json', sa.JSON(), nullable=True),
    sa.Column('created_at', sa.DateTime(timezone=True), nullable=False),
    sa.UniqueConstraint('score_run_id', 'spot_id', 'valid_at', name='uq_score_snapshot_run_spot_valid'),
    sa.CheckConstraint('total_score >= 0 AND total_score <= 100', name='ck_score_snapshot_total_score_range'),
)

confidence_runs = sa.Table(
    'confidence_runs', _metadata,
    sa.Column('id', sa.Integer(), primary_key=True),
    sa.Column('calculated_at', sa.DateTime(timezone=True), nullable=False),
    sa.Column('forecast_cutoff_at', sa.DateTime(timezone=True), nullable=False),
    sa.Column('confidence_engine_version', sa.String(120), nullable=False),
    sa.Column('configuration_hash', sa.String(128), nullable=False),
    sa.Column('status', sa.String(40), nullable=False),
    sa.Column('error_message', sa.Text(), nullable=True),
    sa.Column('metadata_json', sa.JSON(), nullable=True),
    sa.Column('created_at', sa.DateTime(timezone=True), nullable=False),
)

confidence_snapshots = sa.Table(
    'confidence_snapshots', _metadata,
    sa.Column('id', sa.Integer(), primary_key=True),
    sa.Column('confidence_run_id', sa.Integer(), sa.ForeignKey('confidence_runs.id', ondelete='RESTRICT'), nullable=False),
    sa.Column('spot_id', sa.Integer(), sa.ForeignKey('surf_spots.id', ondelete='RESTRICT'), nullable=False),
    sa.Column('valid_at', sa.DateTime(timezone=True), nullable=False),
    sa.Column('confidence_score', sa.Float(), nullable=False),
    sa.Column('confidence_label', sa.String(80), nullable=False),
    sa.Column('provider_agreement_score', sa.Float(), nullable=True),
    sa.Column('data_freshness_score', sa.Float(), nullable=True),
    sa.Column('data_completeness_score', sa.Float(), nullable=True),
    sa.Column('forecast_stability_score', sa.Float(), nullable=True),
    sa.Column('spatial_relevance_score', sa.Float(), nullable=True),
    sa.Column('spot_predictability_score', sa.Float(), nullable=True),
    sa.Column('reasons_json', sa.JSON(), nullable=True),
    sa.Column('created_at', sa.DateTime(timezone=True), nullable=False),
    sa.UniqueConstraint('confidence_run_id', 'spot_id', 'valid_at', name='uq_confidence_snapshot_run_spot_valid'),
    sa.CheckConstraint('confidence_score >= 0 AND confidence_score <= 100', name='ck_confidence_snapshot_score_range'),
)

recommendation_snapshots = sa.Table(
    'recommendation_snapshots', _metadata,
    sa.Column('id', sa.Integer(), primary_key=True),
    sa.Column('recommendation_date', sa.Date(), nullable=False),
    sa.Column('daypart', sa.String(20), nullable=False),
    sa.Column('generated_at', sa.DateTime(timezone=True), nullable=False),
    sa.Column('recommended_spot_id', sa.Integer(), sa.ForeignKey('surf_spots.id', ondelete='RESTRICT'), nullable=True),
    sa.Column('recommended_zone', sa.String(160), nullable=True),
    sa.Column('score', sa.Float(), nullable=True),
    sa.Column('confidence_score', sa.Float(), nullable=True),
    sa.Column('confidence_label', sa.String(80), nullable=True),
    sa.Column('best_window_start', sa.DateTime(timezone=True), nullable=True),
    sa.Column('best_window_end', sa.DateTime(timezone=True), nullable=True),
    sa.Column('ranking_json', sa.JSON(), nullable=True),
    sa.Column('explanation', sa.Text(), nullable=True),
    sa.Column('forecast_cutoff_at', sa.DateTime(timezone=True), nullable=False),
    sa.Column('forecast_run_ids_json', sa.JSON(), nullable=True),
    sa.Column('consensus_run_id', sa.Integer(), sa.ForeignKey('consensus_runs.id', ondelete='RESTRICT'), nullable=True),
    sa.Column('assessment_run_id', sa.Integer(), sa.ForeignKey('spot_assessment_runs.id', ondelete='RESTRICT'), nullable=True),
    sa.Column('score_run_id', sa.Integer(), sa.ForeignKey('spot_score_runs.id', ondelete='RESTRICT'), nullable=True),
    sa.Column('confidence_run_id', sa.Integer(), sa.ForeignKey('confidence_runs.id', ondelete='RESTRICT'), nullable=True),
    sa.Column('spot_rules_version', sa.String(120), nullable=True),
    sa.Column('scoring_engine_version', sa.String(120), nullable=True),
    sa.Column('confidence_engine_version', sa.String(120), nullable=True),
    sa.Column('surfer_profile_version', sa.String(120), nullable=True),
    sa.Column('created_at', sa.DateTime(timezone=True), nullable=False),
    sa.CheckConstraint("daypart IN ('morning','midday','evening')", name='ck_recommendation_snapshot_daypart'),
    sa.CheckConstraint('score IS NULL OR (score >= 0 AND score <= 100)', name='ck_recommendation_snapshot_score_range'),
    sa.CheckConstraint('confidence_score IS NULL OR (confidence_score >= 0 AND confidence_score <= 100)', name='ck_recommendation_snapshot_confidence_range'),
    sa.Index('ix_recommendation_snapshots_date_daypart', 'recommendation_date', 'daypart'),
    sa.Index('ix_recommendation_snapshots_generated_at', 'generated_at'),
)

_NEW_TABLES = [
    provider_publications,
    forecast_runs,
    provider_forecast_points,
    consensus_runs,
    consensus_forecast_points,
    spot_assessment_runs,
    spot_assessment_points,
    spot_score_runs,
    spot_score_snapshots,
    confidence_runs,
    confidence_snapshots,
    recommendation_snapshots,
]

_FETCH_LEDGER_COLUMNS = [
    sa.Column('publication_id', sa.Integer(), nullable=True),
    sa.Column('started_at', sa.DateTime(timezone=True), nullable=True),
    sa.Column('completed_at', sa.DateTime(timezone=True), nullable=True),
    sa.Column('attempt_number', sa.Integer(), nullable=True),
    sa.Column('download_size_bytes', sa.BigInteger(), nullable=True),
    sa.Column('payload_checksum', sa.String(length=128), nullable=True),
    sa.Column('raw_payload_path', sa.String(length=800), nullable=True),
    sa.Column('raw_file_deleted_at', sa.DateTime(timezone=True), nullable=True),
    sa.Column('normalized_records_count', sa.Integer(), nullable=True),
    sa.Column('error_code', sa.String(length=120), nullable=True),
    sa.Column('error_message', sa.Text(), nullable=True),
    sa.Column('metadata_json', sa.JSON(), nullable=True),
    sa.Column('created_at', sa.DateTime(timezone=True), nullable=True),
    sa.Column('updated_at', sa.DateTime(timezone=True), nullable=True),
]


def upgrade():
    bind = op.get_bind()
    for table in _NEW_TABLES:
        table.create(bind, checkfirst=True)

    with op.batch_alter_table('provider_fetches') as batch:
        for column in _FETCH_LEDGER_COLUMNS:
            batch.add_column(column.copy())
        batch.create_foreign_key('fk_provider_fetches_publication_id', 'provider_publications', ['publication_id'], ['id'], ondelete='RESTRICT')
        batch.create_index('ix_provider_fetches_publication_id', ['publication_id'])
        batch.create_unique_constraint('uq_provider_fetch_publication_attempt', ['publication_id', 'attempt_number'])


def downgrade():
    with op.batch_alter_table('provider_fetches') as batch:
        batch.drop_constraint('uq_provider_fetch_publication_attempt', type_='unique')
        batch.drop_index('ix_provider_fetches_publication_id')
        batch.drop_constraint('fk_provider_fetches_publication_id', type_='foreignkey')
        for column in reversed([c.name for c in _FETCH_LEDGER_COLUMNS]):
            batch.drop_column(column)

    bind = op.get_bind()
    for table in reversed(_NEW_TABLES):
        table.drop(bind, checkfirst=True)
