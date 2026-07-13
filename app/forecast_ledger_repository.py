from __future__ import annotations

# Compatibility facade for the PR 1 ledger repositories. New code should import
# from app.repositories.<domain>_repository; existing tests/imports can keep using
# app.forecast_ledger_repository during the branch transition.
from .repositories.ledger_utils import utc_now
from .repositories.provider_publication_repository import create_publication, get_publication_by_identity, list_publications
from .repositories.provider_fetch_repository import create_fetch_attempt, mark_fetch_status
from .repositories.forecast_repository import create_forecast_run, get_forecast_run, insert_forecast_points, list_points_for_run, list_versions_for_spot_and_valid_time
from .repositories.consensus_repository import ConsensusRunTransitionError, count_consensus_points_for_run, create_consensus_points, create_consensus_run, find_equivalent_completed_run, get_consensus_point, get_consensus_run, insert_consensus_points, latest_consensus_runs, list_consensus_points_for_run, mark_consensus_run_status
from .repositories.spot_assessment_repository import create_spot_assessment_points, create_spot_assessment_run, mark_spot_assessment_run_status
from .repositories.spot_score_repository import SpotScoreRunTransitionError, count_spot_score_runs, count_spot_score_snapshots_for_run, create_spot_score_run, create_spot_score_snapshots, find_equivalent_completed_score, find_latest_equivalent_score, get_spot_score_run, get_spot_score_snapshot, latest_spot_score_runs, list_spot_score_snapshots_for_run, mark_spot_score_run_status, next_spot_score_recalculation_sequence
from .repositories.confidence_repository import create_confidence_run, create_confidence_snapshots
from .repositories.recommendation_repository import create_recommendation_snapshot, list_recommendation_versions

__all__ = [
    'utc_now',
    'create_publication',
    'get_publication_by_identity',
    'list_publications',
    'create_fetch_attempt',
    'mark_fetch_status',
    'create_forecast_run',
    'get_forecast_run',
    'insert_forecast_points',
    'list_points_for_run',
    'list_versions_for_spot_and_valid_time',
    'create_consensus_run',
    'create_consensus_points',
    'insert_consensus_points',
    'mark_consensus_run_status',
    'find_equivalent_completed_run',
    'list_consensus_points_for_run',
    'get_consensus_point',
    'latest_consensus_runs',
    'get_consensus_run',
    'count_consensus_points_for_run',
    'ConsensusRunTransitionError',
    'create_spot_assessment_run',
    'create_spot_assessment_points',
    'mark_spot_assessment_run_status',
    'create_spot_score_run',
    'create_spot_score_snapshots',
    'mark_spot_score_run_status',
    'get_spot_score_run',
    'find_equivalent_completed_score',
    'find_latest_equivalent_score',
    'next_spot_score_recalculation_sequence',
    'get_spot_score_snapshot',
    'count_spot_score_snapshots_for_run',
    'list_spot_score_snapshots_for_run',
    'count_spot_score_runs',
    'latest_spot_score_runs',
    'SpotScoreRunTransitionError',
    'create_confidence_run',
    'create_confidence_snapshots',
    'create_recommendation_snapshot',
    'list_recommendation_versions',
]
