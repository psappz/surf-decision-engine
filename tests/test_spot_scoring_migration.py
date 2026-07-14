import os
import subprocess
from pathlib import Path

import sqlalchemy as sa
from sqlalchemy import inspect

PROJECT_ROOT = Path(__file__).resolve().parents[1]


def _run_alembic(database_url: str, *args: str):
    return subprocess.run(
        ['.venv/bin/alembic', *args], cwd=PROJECT_ROOT,
        env={**os.environ, 'DATABASE_URL': database_url},
        text=True, capture_output=True, timeout=120,
    )


def _alembic(database_url: str, *args: str):
    result = _run_alembic(database_url, *args)
    assert result.returncode == 0, result.stdout + result.stderr


def _seed_legacy_score_snapshot(
    engine: sa.Engine,
    *,
    point_timestamp: str,
    snapshot_timestamp: str,
):
    with engine.begin() as connection:
        connection.execute(sa.text("""
            INSERT INTO surf_spots
                (id, code, slug, name, latitude, longitude,
                 is_active_for_recommendations, updated_at)
            VALUES (1, 'TST', 'test', 'Test', 37, -9, 1, :now)
        """), {'now': point_timestamp})
        connection.execute(sa.text("""
            INSERT INTO consensus_runs
                (id, calculated_at, forecast_cutoff_at, consensus_engine_version,
                 configuration_hash, status, created_at)
            VALUES (1, :now, :now, 'cons-v1', 'cons-hash', 'completed', :now)
        """), {'now': point_timestamp})
        connection.execute(sa.text("""
            INSERT INTO spot_assessment_runs
                (id, consensus_run_id, calculated_at, spot_rules_version,
                 spot_rules_hash, spot_intelligence_engine_version,
                 configuration_hash, calculation_scope_hash,
                 recalculation_sequence, status, created_at)
            VALUES (1, 1, :now, 'rules-v1', 'rules-hash', 'spot-v1',
                    'spot-config', 'scope', 0, 'completed', :now)
        """), {'now': point_timestamp})
        connection.execute(sa.text("""
            INSERT INTO spot_assessment_points
                (id, assessment_run_id, spot_id, valid_at, created_at)
            VALUES (7, 1, 1, :valid_at, :now)
        """), {'valid_at': point_timestamp, 'now': point_timestamp})
        connection.execute(sa.text("""
            INSERT INTO spot_score_runs
                (id, assessment_run_id, calculated_at, scoring_engine_version,
                 scoring_configuration_hash, surfer_profile_version,
                 surfer_profile_hash, status, created_at)
            VALUES (1, 1, :now, 'score-v1', 'score-config', 'profile-v1',
                    'profile-hash', 'completed', :now)
        """), {'now': point_timestamp})
        connection.execute(sa.text("""
            INSERT INTO spot_score_snapshots
                (id, score_run_id, spot_id, valid_at, total_score,
                 condition_classification, created_at)
            VALUES (1, 1, 1, :valid_at, 50, 'legacy', :now)
        """), {'valid_at': snapshot_timestamp, 'now': point_timestamp})


def test_0008_schema_and_fresh_downgrade_to_0007(tmp_path):
    url = f"sqlite:///{tmp_path / 'fresh.db'}"
    _alembic(url, 'upgrade', 'head')
    engine = sa.create_engine(url)
    inspector = inspect(engine)
    run_columns = {column['name']: column for column in inspector.get_columns('spot_score_runs')}
    snapshot_columns = {column['name'] for column in inspector.get_columns('spot_score_snapshots')}
    assert {'calculation_scope_hash', 'recalculation_sequence'} <= set(run_columns)
    assert run_columns['scoring_engine_version']['type'].length == 80
    assert run_columns['surfer_profile_version']['type'].length == 80
    assert 'assessment_point_id' in snapshot_columns
    assert {'ix_score_run_equivalence', 'ix_spot_score_runs_status'} <= {
        index['name'] for index in inspector.get_indexes('spot_score_runs')
    }
    assert {'ix_spot_score_snapshots_assessment_point', 'ix_spot_score_snapshots_spot_valid'} <= {
        index['name'] for index in inspector.get_indexes('spot_score_snapshots')
    }
    foreign_keys = {fk['name']: fk for fk in inspector.get_foreign_keys('spot_score_snapshots')}
    point_fk = foreign_keys['fk_score_snapshot_assessment_point_id']
    assert point_fk['referred_table'] == 'spot_assessment_points'
    assert point_fk['options'].get('ondelete') == 'RESTRICT'
    check_names = {check['name'] for check in inspector.get_check_constraints('spot_score_snapshots')}
    assert {'ck_score_snapshot_wind_speed_score_range', 'ck_score_snapshot_penalty_nonnegative'} <= check_names
    _alembic(url, 'downgrade', '0007_spot_assessment_force_runs')
    assert 'assessment_point_id' not in {
        column['name'] for column in inspect(engine).get_columns('spot_score_snapshots')
    }
    engine.dispose()


def test_0008_backfills_verifiable_legacy_snapshot_provenance(tmp_path):
    url = f"sqlite:///{tmp_path / 'legacy.db'}"
    _alembic(url, 'upgrade', '0007_spot_assessment_force_runs')
    engine = sa.create_engine(url)
    timestamp = '2026-07-13 09:00:00'
    _seed_legacy_score_snapshot(
        engine,
        point_timestamp=timestamp,
        snapshot_timestamp=timestamp,
    )
    engine.dispose()
    _alembic(url, 'upgrade', 'head')
    engine = sa.create_engine(url)
    with engine.connect() as connection:
        assert connection.execute(sa.text(
            'SELECT assessment_point_id FROM spot_score_snapshots WHERE id = 1'
        )).scalar_one() == 7
        run = connection.execute(sa.text(
            'SELECT calculation_scope_hash, recalculation_sequence FROM spot_score_runs WHERE id = 1'
        )).one()
        assert tuple(run) == ('legacy-unscoped', 0)
    engine.dispose()


def test_0008_failed_provenance_validation_can_be_repaired_and_retried(tmp_path):
    url = f"sqlite:///{tmp_path / 'retry.db'}"
    _alembic(url, 'upgrade', '0007_spot_assessment_force_runs')
    engine = sa.create_engine(url)
    _seed_legacy_score_snapshot(
        engine,
        point_timestamp='2026-07-13 09:00:00',
        snapshot_timestamp='2026-07-13 10:00:00',
    )
    engine.dispose()

    failed = _run_alembic(url, 'upgrade', 'head')
    assert failed.returncode != 0
    assert '0008 cannot infer assessment_point_id for 1 legacy score snapshot(s)' in (
        failed.stdout + failed.stderr
    )

    engine = sa.create_engine(url)
    with engine.begin() as connection:
        assert connection.execute(sa.text('SELECT version_num FROM alembic_version')).scalar_one() == (
            '0007_spot_assessment_force_runs'
        )
        assert not {
            table for table in inspect(connection).get_table_names()
            if table.startswith('_alembic_tmp_')
        }
        connection.execute(sa.text('DELETE FROM spot_score_snapshots WHERE id = 1'))
    engine.dispose()

    _alembic(url, 'upgrade', 'head')
    engine = sa.create_engine(url)
    inspector = inspect(engine)
    assert 'assessment_point_id' in {
        column['name'] for column in inspector.get_columns('spot_score_snapshots')
    }
    assert not {
        table for table in inspector.get_table_names() if table.startswith('_alembic_tmp_')
    }
    engine.dispose()

    _alembic(url, 'downgrade', '0007_spot_assessment_force_runs')
    engine = sa.create_engine(url)
    inspector = inspect(engine)
    assert 'assessment_point_id' not in {
        column['name'] for column in inspector.get_columns('spot_score_snapshots')
    }
    assert not {
        table for table in inspector.get_table_names() if table.startswith('_alembic_tmp_')
    }
    engine.dispose()
