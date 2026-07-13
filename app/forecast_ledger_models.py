from __future__ import annotations

from datetime import date, datetime

from sqlalchemy import CheckConstraint, ForeignKey, Index, String, Text, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column, relationship
from sqlalchemy.types import Date, DateTime, Float, Integer, JSON, BigInteger

from .models import Base


class ProviderPublication(Base):
    __tablename__ = 'provider_publications'
    __table_args__ = (
        UniqueConstraint('provider_name', 'dataset_id', 'publication_identity', name='uq_provider_publication_identity'),
        Index('ix_provider_publications_provider_name', 'provider_name'),
        Index('ix_provider_publications_publication_identity', 'publication_identity'),
        Index('ix_provider_publications_model_cycle_at', 'model_cycle_at'),
        Index('ix_provider_publications_status', 'status'),
        Index('ix_provider_publications_detected_at', 'detected_at'),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    provider_name: Mapped[str] = mapped_column(String(100), nullable=False)
    product_id: Mapped[str | None] = mapped_column(String(180), nullable=True)
    dataset_id: Mapped[str] = mapped_column(String(220), nullable=False, default='')
    publication_identity: Mapped[str] = mapped_column(String(500), nullable=False)
    model_cycle_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    source_updated_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    latest_valid_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    detected_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    status: Mapped[str] = mapped_column(String(40), nullable=False)
    metadata_json: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)


class ForecastRun(Base):
    __tablename__ = 'forecast_runs'
    __table_args__ = (
        UniqueConstraint('fetch_id', 'normalizer_version', 'normalizer_configuration_hash', name='uq_forecast_run_fetch_normalizer_config'),
        Index('ix_forecast_runs_provider_name', 'provider_name'),
        Index('ix_forecast_runs_publication_id', 'publication_id'),
        Index('ix_forecast_runs_fetch_id', 'fetch_id'),
        Index('ix_forecast_runs_issued_at', 'issued_at'),
        Index('ix_forecast_runs_fetched_at', 'fetched_at'),
        Index('ix_forecast_runs_status', 'status'),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    provider_name: Mapped[str] = mapped_column(String(100), nullable=False)
    publication_id: Mapped[int | None] = mapped_column(ForeignKey('provider_publications.id', ondelete='RESTRICT'), nullable=True)
    fetch_id: Mapped[int | None] = mapped_column(ForeignKey('provider_fetches.id', ondelete='RESTRICT'), nullable=True)
    issued_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    fetched_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    normalized_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    geographic_bounds_json: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    temporal_bounds_json: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    schema_version: Mapped[str] = mapped_column(String(40), nullable=False)
    normalizer_version: Mapped[str] = mapped_column(String(80), nullable=False)
    normalizer_configuration_hash: Mapped[str] = mapped_column(String(128), nullable=False)
    status: Mapped[str] = mapped_column(String(40), nullable=False)
    error_message: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)


class ProviderForecastPoint(Base):
    __tablename__ = 'provider_forecast_points'
    __table_args__ = (
        UniqueConstraint('forecast_run_id', 'spot_id', 'sample_point_id', 'valid_at', name='uq_provider_point_run_spot_sample_valid'),
        CheckConstraint('wave_height IS NULL OR wave_height >= 0', name='ck_provider_point_wave_height_nonnegative'),
        CheckConstraint('wave_period IS NULL OR wave_period >= 0', name='ck_provider_point_wave_period_nonnegative'),
        CheckConstraint('wind_speed IS NULL OR wind_speed >= 0', name='ck_provider_point_wind_speed_nonnegative'),
        Index('ix_provider_forecast_points_run', 'forecast_run_id'),
        Index('ix_provider_forecast_points_spot_valid', 'spot_id', 'valid_at'),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    forecast_run_id: Mapped[int] = mapped_column(ForeignKey('forecast_runs.id', ondelete='RESTRICT'), nullable=False)
    spot_id: Mapped[int] = mapped_column(ForeignKey('surf_spots.id', ondelete='RESTRICT'), nullable=False)
    sample_point_id: Mapped[str] = mapped_column(String(120), nullable=False, default='')
    valid_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    wave_height: Mapped[float | None] = mapped_column(Float, nullable=True)
    wave_direction: Mapped[float | None] = mapped_column(Float, nullable=True)
    wave_period: Mapped[float | None] = mapped_column(Float, nullable=True)
    swell_wave_height: Mapped[float | None] = mapped_column(Float, nullable=True)
    swell_wave_direction: Mapped[float | None] = mapped_column(Float, nullable=True)
    swell_wave_period: Mapped[float | None] = mapped_column(Float, nullable=True)
    wind_wave_height: Mapped[float | None] = mapped_column(Float, nullable=True)
    wind_wave_direction: Mapped[float | None] = mapped_column(Float, nullable=True)
    wind_wave_period: Mapped[float | None] = mapped_column(Float, nullable=True)
    wind_speed: Mapped[float | None] = mapped_column(Float, nullable=True)
    wind_direction: Mapped[float | None] = mapped_column(Float, nullable=True)
    wind_gust: Mapped[float | None] = mapped_column(Float, nullable=True)
    water_temperature: Mapped[float | None] = mapped_column(Float, nullable=True)
    current_speed: Mapped[float | None] = mapped_column(Float, nullable=True)
    current_direction: Mapped[float | None] = mapped_column(Float, nullable=True)
    tide_height: Mapped[float | None] = mapped_column(Float, nullable=True)
    tide_state: Mapped[str | None] = mapped_column(String(40), nullable=True)
    raw_values_json: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    quality_flags_json: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)


class ConsensusRun(Base):
    __tablename__ = 'consensus_runs'
    __table_args__ = (
        Index('ix_consensus_runs_calculated_at', 'calculated_at'),
        Index('ix_consensus_runs_forecast_cutoff_at', 'forecast_cutoff_at'),
        Index('ix_consensus_runs_status', 'status'),
    )
    id: Mapped[int] = mapped_column(primary_key=True)
    calculated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    forecast_cutoff_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    consensus_engine_version: Mapped[str] = mapped_column(String(80), nullable=False)
    configuration_hash: Mapped[str] = mapped_column(String(128), nullable=False)
    status: Mapped[str] = mapped_column(String(40), nullable=False)
    error_message: Mapped[str | None] = mapped_column(Text, nullable=True)
    metadata_json: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)


class ConsensusForecastPoint(Base):
    __tablename__ = 'consensus_forecast_points'
    __table_args__ = (
        UniqueConstraint('consensus_run_id', 'spot_id', 'valid_at', name='uq_consensus_point_run_spot_valid'),
        CheckConstraint('provider_count >= 0', name='ck_consensus_provider_count_nonnegative'),
        Index('ix_consensus_forecast_points_run', 'consensus_run_id'),
        Index('ix_consensus_forecast_points_spot_valid', 'spot_id', 'valid_at'),
    )
    id: Mapped[int] = mapped_column(primary_key=True)
    consensus_run_id: Mapped[int] = mapped_column(ForeignKey('consensus_runs.id', ondelete='RESTRICT'), nullable=False)
    spot_id: Mapped[int] = mapped_column(ForeignKey('surf_spots.id', ondelete='RESTRICT'), nullable=False)
    valid_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    wave_height: Mapped[float | None] = mapped_column(Float, nullable=True)
    wave_direction: Mapped[float | None] = mapped_column(Float, nullable=True)
    wave_period: Mapped[float | None] = mapped_column(Float, nullable=True)
    wind_speed: Mapped[float | None] = mapped_column(Float, nullable=True)
    wind_direction: Mapped[float | None] = mapped_column(Float, nullable=True)
    tide_height: Mapped[float | None] = mapped_column(Float, nullable=True)
    swell_wave_height: Mapped[float | None] = mapped_column(Float, nullable=True)
    swell_wave_direction: Mapped[float | None] = mapped_column(Float, nullable=True)
    swell_wave_period: Mapped[float | None] = mapped_column(Float, nullable=True)
    wind_wave_height: Mapped[float | None] = mapped_column(Float, nullable=True)
    wind_wave_direction: Mapped[float | None] = mapped_column(Float, nullable=True)
    wind_wave_period: Mapped[float | None] = mapped_column(Float, nullable=True)
    wind_gust: Mapped[float | None] = mapped_column(Float, nullable=True)
    water_temperature: Mapped[float | None] = mapped_column(Float, nullable=True)
    current_speed: Mapped[float | None] = mapped_column(Float, nullable=True)
    current_direction: Mapped[float | None] = mapped_column(Float, nullable=True)
    provider_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    provider_ids_json: Mapped[list | None] = mapped_column(JSON, nullable=True)
    agreement_score: Mapped[float | None] = mapped_column(Float, nullable=True)
    freshness_score: Mapped[float | None] = mapped_column(Float, nullable=True)
    completeness_score: Mapped[float | None] = mapped_column(Float, nullable=True)
    confidence_input_score: Mapped[float | None] = mapped_column(Float, nullable=True)
    calculation_details_json: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)


class SpotAssessmentRun(Base):
    __tablename__ = 'spot_assessment_runs'
    __table_args__ = (
        UniqueConstraint('consensus_run_id', 'spot_rules_hash', 'spot_intelligence_engine_version', 'configuration_hash', 'calculation_scope_hash', 'recalculation_sequence', name='uq_assessment_run_input_scope_sequence'),
        Index('ix_spot_assessment_runs_consensus_run_id', 'consensus_run_id'),
        Index('ix_spot_assessment_runs_status', 'status'),
        Index('ix_assessment_run_equivalence', 'consensus_run_id', 'spot_rules_hash', 'spot_intelligence_engine_version', 'configuration_hash'),
    )
    id: Mapped[int] = mapped_column(primary_key=True)
    consensus_run_id: Mapped[int] = mapped_column(ForeignKey('consensus_runs.id', ondelete='RESTRICT'), nullable=False)
    calculated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    spot_rules_version: Mapped[str] = mapped_column(String(80), nullable=False)
    spot_rules_hash: Mapped[str] = mapped_column(String(128), nullable=False)
    spot_intelligence_engine_version: Mapped[str] = mapped_column(String(80), nullable=False)
    configuration_hash: Mapped[str] = mapped_column(String(128), nullable=False)
    calculation_scope_hash: Mapped[str] = mapped_column(String(128), nullable=False, default='legacy-unscoped')
    recalculation_sequence: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    status: Mapped[str] = mapped_column(String(40), nullable=False)
    error_message: Mapped[str | None] = mapped_column(Text, nullable=True)
    metadata_json: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)


class SpotAssessmentPoint(Base):
    __tablename__ = 'spot_assessment_points'
    __table_args__ = (
        UniqueConstraint('assessment_run_id', 'spot_id', 'valid_at', name='uq_assessment_point_run_spot_valid'),
        CheckConstraint('breaking_wave_min IS NULL OR breaking_wave_min >= 0', name='ck_assessment_breaking_min_nonnegative'),
        CheckConstraint('breaking_wave_max IS NULL OR breaking_wave_min IS NULL OR breaking_wave_max >= breaking_wave_min', name='ck_assessment_breaking_max_gte_min'),
    )
    id: Mapped[int] = mapped_column(primary_key=True)
    assessment_run_id: Mapped[int] = mapped_column(ForeignKey('spot_assessment_runs.id', ondelete='RESTRICT'), nullable=False)
    spot_id: Mapped[int] = mapped_column(ForeignKey('surf_spots.id', ondelete='RESTRICT'), nullable=False)
    valid_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    swell_direction_fit: Mapped[float | None] = mapped_column(Float, nullable=True)
    swell_height_fit: Mapped[float | None] = mapped_column(Float, nullable=True)
    period_fit: Mapped[float | None] = mapped_column(Float, nullable=True)
    wind_direction_fit: Mapped[float | None] = mapped_column(Float, nullable=True)
    wind_speed_fit: Mapped[float | None] = mapped_column(Float, nullable=True)
    tide_fit: Mapped[float | None] = mapped_column(Float, nullable=True)
    exposure_adjustment: Mapped[float | None] = mapped_column(Float, nullable=True)
    shelter_adjustment: Mapped[float | None] = mapped_column(Float, nullable=True)
    breaking_wave_min: Mapped[float | None] = mapped_column(Float, nullable=True)
    breaking_wave_max: Mapped[float | None] = mapped_column(Float, nullable=True)
    hazard_flags_json: Mapped[list | None] = mapped_column(JSON, nullable=True)
    uncertainty_factors_json: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    factor_details_json: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)


class SpotScoreRun(Base):
    __tablename__ = 'spot_score_runs'
    __table_args__ = (
        UniqueConstraint('assessment_run_id', 'scoring_engine_version', 'scoring_configuration_hash', 'surfer_profile_version', 'surfer_profile_hash', name='uq_score_run_input_version'),
    )
    id: Mapped[int] = mapped_column(primary_key=True)
    assessment_run_id: Mapped[int] = mapped_column(ForeignKey('spot_assessment_runs.id', ondelete='RESTRICT'), nullable=False)
    calculated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    scoring_engine_version: Mapped[str] = mapped_column(String(80), nullable=False)
    scoring_configuration_hash: Mapped[str] = mapped_column(String(128), nullable=False)
    surfer_profile_version: Mapped[str] = mapped_column(String(80), nullable=False)
    surfer_profile_hash: Mapped[str] = mapped_column(String(128), nullable=False)
    status: Mapped[str] = mapped_column(String(40), nullable=False)
    error_message: Mapped[str | None] = mapped_column(Text, nullable=True)
    metadata_json: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)


class SpotScoreSnapshot(Base):
    __tablename__ = 'spot_score_snapshots'
    __table_args__ = (
        UniqueConstraint('score_run_id', 'spot_id', 'valid_at', name='uq_score_snapshot_run_spot_valid'),
        CheckConstraint('total_score IS NULL OR (total_score >= 0 AND total_score <= 100)', name='ck_score_snapshot_total_range'),
    )
    id: Mapped[int] = mapped_column(primary_key=True)
    score_run_id: Mapped[int] = mapped_column(ForeignKey('spot_score_runs.id', ondelete='RESTRICT'), nullable=False)
    spot_id: Mapped[int] = mapped_column(ForeignKey('surf_spots.id', ondelete='RESTRICT'), nullable=False)
    valid_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    total_score: Mapped[float | None] = mapped_column(Float, nullable=True)
    condition_classification: Mapped[str | None] = mapped_column(String(80), nullable=True)
    swell_direction_score: Mapped[float | None] = mapped_column(Float, nullable=True)
    swell_height_score: Mapped[float | None] = mapped_column(Float, nullable=True)
    period_score: Mapped[float | None] = mapped_column(Float, nullable=True)
    wind_direction_score: Mapped[float | None] = mapped_column(Float, nullable=True)
    wind_speed_score: Mapped[float | None] = mapped_column(Float, nullable=True)
    tide_score: Mapped[float | None] = mapped_column(Float, nullable=True)
    safety_score: Mapped[float | None] = mapped_column(Float, nullable=True)
    penalty_total: Mapped[float | None] = mapped_column(Float, nullable=True)
    penalties_json: Mapped[list | None] = mapped_column(JSON, nullable=True)
    positive_factors_json: Mapped[list | None] = mapped_column(JSON, nullable=True)
    negative_factors_json: Mapped[list | None] = mapped_column(JSON, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)


class ConfidenceRun(Base):
    __tablename__ = 'confidence_runs'
    __table_args__ = (Index('ix_confidence_runs_status', 'status'),)
    id: Mapped[int] = mapped_column(primary_key=True)
    calculated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    forecast_cutoff_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    confidence_engine_version: Mapped[str] = mapped_column(String(80), nullable=False)
    configuration_hash: Mapped[str] = mapped_column(String(128), nullable=False)
    status: Mapped[str] = mapped_column(String(40), nullable=False)
    error_message: Mapped[str | None] = mapped_column(Text, nullable=True)
    metadata_json: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)


class ConfidenceSnapshot(Base):
    __tablename__ = 'confidence_snapshots'
    __table_args__ = (
        UniqueConstraint('confidence_run_id', 'spot_id', 'valid_at', name='uq_confidence_snapshot_run_spot_valid'),
        CheckConstraint('confidence_score IS NULL OR (confidence_score >= 0 AND confidence_score <= 100)', name='ck_confidence_snapshot_score_range'),
    )
    id: Mapped[int] = mapped_column(primary_key=True)
    confidence_run_id: Mapped[int] = mapped_column(ForeignKey('confidence_runs.id', ondelete='RESTRICT'), nullable=False)
    spot_id: Mapped[int] = mapped_column(ForeignKey('surf_spots.id', ondelete='RESTRICT'), nullable=False)
    valid_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    confidence_score: Mapped[float | None] = mapped_column(Float, nullable=True)
    confidence_label: Mapped[str | None] = mapped_column(String(80), nullable=True)
    provider_agreement_score: Mapped[float | None] = mapped_column(Float, nullable=True)
    data_freshness_score: Mapped[float | None] = mapped_column(Float, nullable=True)
    data_completeness_score: Mapped[float | None] = mapped_column(Float, nullable=True)
    forecast_stability_score: Mapped[float | None] = mapped_column(Float, nullable=True)
    spatial_relevance_score: Mapped[float | None] = mapped_column(Float, nullable=True)
    spot_predictability_score: Mapped[float | None] = mapped_column(Float, nullable=True)
    reasons_json: Mapped[list | None] = mapped_column(JSON, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)


class RecommendationSnapshot(Base):
    __tablename__ = 'recommendation_snapshots'
    __table_args__ = (
        Index('ix_recommendation_snapshots_date_daypart', 'recommendation_date', 'daypart'),
        Index('ix_recommendation_snapshots_generated_at', 'generated_at'),
    )
    id: Mapped[int] = mapped_column(primary_key=True)
    recommendation_date: Mapped[date] = mapped_column(Date, nullable=False)
    daypart: Mapped[str] = mapped_column(String(20), nullable=False)
    generated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    recommended_spot_id: Mapped[int | None] = mapped_column(ForeignKey('surf_spots.id', ondelete='RESTRICT'), nullable=True)
    recommended_zone: Mapped[str | None] = mapped_column(String(160), nullable=True)
    score: Mapped[float | None] = mapped_column(Float, nullable=True)
    confidence_score: Mapped[float | None] = mapped_column(Float, nullable=True)
    confidence_label: Mapped[str | None] = mapped_column(String(80), nullable=True)
    best_window_start: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    best_window_end: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    ranking_json: Mapped[list | None] = mapped_column(JSON, nullable=True)
    explanation: Mapped[str | None] = mapped_column(Text, nullable=True)
    forecast_cutoff_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    forecast_run_ids_json: Mapped[list | None] = mapped_column(JSON, nullable=True)
    consensus_run_id: Mapped[int | None] = mapped_column(ForeignKey('consensus_runs.id', ondelete='RESTRICT'), nullable=True)
    assessment_run_id: Mapped[int | None] = mapped_column(ForeignKey('spot_assessment_runs.id', ondelete='RESTRICT'), nullable=True)
    score_run_id: Mapped[int | None] = mapped_column(ForeignKey('spot_score_runs.id', ondelete='RESTRICT'), nullable=True)
    confidence_run_id: Mapped[int | None] = mapped_column(ForeignKey('confidence_runs.id', ondelete='RESTRICT'), nullable=True)
    spot_rules_version: Mapped[str | None] = mapped_column(String(80), nullable=True)
    scoring_engine_version: Mapped[str | None] = mapped_column(String(80), nullable=True)
    confidence_engine_version: Mapped[str | None] = mapped_column(String(80), nullable=True)
    surfer_profile_version: Mapped[str | None] = mapped_column(String(80), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
