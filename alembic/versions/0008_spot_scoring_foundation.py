"""harden append-only spot scoring foundation

Revision ID: 0008_spot_scoring_foundation
Revises: 0007_spot_assessment_force_runs
Create Date: 2026-07-13
"""
import hashlib
import json

import sqlalchemy as sa
from alembic import op

revision = '0008_spot_scoring_foundation'
down_revision = '0007_spot_assessment_force_runs'
branch_labels = None
depends_on = None

_SCORE_COLUMNS = (
    'swell_direction_score', 'swell_height_score', 'period_score',
    'wind_direction_score', 'wind_speed_score', 'tide_score', 'safety_score',
)


def _hash(payload) -> str:
    body = json.dumps(payload, sort_keys=True, separators=(',', ':'), ensure_ascii=True)
    return hashlib.sha256(body.encode()).hexdigest()


def _count(bind, sql: str) -> int:
    return int(bind.execute(sa.text(sql)).scalar_one())


def _upgrade_preflight(bind) -> None:
    checks = (
        ("""
            SELECT COUNT(*) FROM spot_score_snapshots AS ss
            JOIN spot_score_runs AS sr ON sr.id = ss.score_run_id
            LEFT JOIN spot_assessment_points AS ap
              ON ap.assessment_run_id = sr.assessment_run_id
             AND ap.spot_id = ss.spot_id AND ap.valid_at = ss.valid_at
            WHERE ap.id IS NULL
        """, 'cannot infer assessment-point provenance'),
        ("""
            SELECT COUNT(*) FROM spot_score_runs
            WHERE length(scoring_engine_version) > 80
               OR length(surfer_profile_version) > 80
        """, 'engine/profile version exceeds 80 characters'),
        ("""
            SELECT COUNT(*) FROM spot_score_snapshots
            WHERE penalty_total < 0 OR penalty_total > 100
        """, 'penalty_total is outside 0..100'),
        ("""
            SELECT COUNT(*) FROM spot_score_snapshots
            WHERE swell_direction_score < 0 OR swell_direction_score > 100
               OR swell_height_score < 0 OR swell_height_score > 100
               OR period_score < 0 OR period_score > 100
               OR wind_direction_score < 0 OR wind_direction_score > 100
               OR wind_speed_score < 0 OR wind_speed_score > 100
               OR tide_score < 0 OR tide_score > 100
               OR safety_score < 0 OR safety_score > 100
        """, 'component score is outside 0..100'),
        ("""
            SELECT COUNT(*) FROM spot_score_runs AS sr
            WHERE sr.status = 'completed' AND (
                (SELECT COUNT(*) FROM spot_assessment_points ap
                  WHERE ap.assessment_run_id = sr.assessment_run_id) = 0
                OR
                (SELECT COUNT(*) FROM spot_score_snapshots ss
                  WHERE ss.score_run_id = sr.id) !=
                (SELECT COUNT(*) FROM spot_assessment_points ap
                  WHERE ap.assessment_run_id = sr.assessment_run_id)
                OR EXISTS (
                    SELECT 1 FROM spot_assessment_points ap
                    WHERE ap.assessment_run_id = sr.assessment_run_id
                      AND NOT EXISTS (
                          SELECT 1 FROM spot_score_snapshots ss
                          WHERE ss.score_run_id = sr.id
                            AND ss.spot_id = ap.spot_id
                            AND ss.valid_at = ap.valid_at
                      )
                )
            )
        """, 'completed legacy run does not exactly cover its assessment scope'),
    )
    for sql, reason in checks:
        count = _count(bind, sql)
        if count:
            raise RuntimeError(
                f'0008 preflight rejected {count} legacy row(s): {reason}; '
                'repair or remove the business rows before retrying'
            )


def upgrade():
    bind = op.get_bind()
    # All data-dependent failures are checked before SQLite batch DDL so a
    # repair-and-retry never requires deleting _alembic_tmp_* artifacts.
    _upgrade_preflight(bind)

    with op.batch_alter_table('spot_score_runs') as batch:
        batch.drop_constraint('uq_score_run_assessment_engine_config_profile', type_='unique')
        batch.alter_column(
            'scoring_engine_version', existing_type=sa.String(length=120),
            type_=sa.String(length=80), existing_nullable=False,
        )
        batch.alter_column(
            'surfer_profile_version', existing_type=sa.String(length=120),
            type_=sa.String(length=80), existing_nullable=False,
        )
        batch.add_column(sa.Column('scoring_configuration_json', sa.JSON(), nullable=True))
        batch.add_column(sa.Column('surfer_profile_name', sa.String(length=80), nullable=True))
        batch.add_column(sa.Column('surfer_profile_json', sa.JSON(), nullable=True))
        batch.add_column(sa.Column('calculation_scope_hash', sa.String(length=128), nullable=True))
        batch.add_column(sa.Column('calculation_scope_json', sa.JSON(), nullable=True))
        batch.add_column(sa.Column('recalculation_sequence', sa.Integer(), nullable=False, server_default='0'))

    runs = sa.Table('spot_score_runs', sa.MetaData(), autoload_with=bind)
    points = sa.Table('spot_assessment_points', sa.MetaData(), autoload_with=bind)
    for run in bind.execute(sa.select(runs)).mappings():
        scope = sorted(bind.execute(
            sa.select(points.c.id).where(points.c.assessment_run_id == run['assessment_run_id'])
        ).scalars())
        config_payload = {'legacy_hash': run['scoring_configuration_hash']}
        profile_payload = {'legacy_hash': run['surfer_profile_hash']}
        bind.execute(sa.update(runs).where(runs.c.id == run['id']).values(
            scoring_configuration_json=config_payload,
            scoring_configuration_hash=_hash(config_payload),
            surfer_profile_name='legacy-unknown',
            surfer_profile_json=profile_payload,
            surfer_profile_hash=_hash(profile_payload),
            calculation_scope_json=scope,
            calculation_scope_hash=_hash({'assessment_point_ids': scope}),
        ))

    with op.batch_alter_table('spot_score_runs') as batch:
        for name, existing_type in (
            ('scoring_configuration_json', sa.JSON()),
            ('surfer_profile_name', sa.String(length=80)),
            ('surfer_profile_json', sa.JSON()),
            ('calculation_scope_hash', sa.String(length=128)),
            ('calculation_scope_json', sa.JSON()),
        ):
            batch.alter_column(name, existing_type=existing_type, nullable=False)
        batch.create_check_constraint('ck_score_run_sequence_nonnegative', 'recalculation_sequence >= 0')
        batch.create_unique_constraint(
            'uq_score_run_input_scope_sequence',
            ['assessment_run_id', 'scoring_engine_version', 'scoring_configuration_hash',
             'surfer_profile_version', 'surfer_profile_hash', 'calculation_scope_hash',
             'recalculation_sequence'],
        )
        batch.create_index('ix_spot_score_runs_assessment_run_id', ['assessment_run_id'], unique=False)
        batch.create_index('ix_spot_score_runs_status', ['status'], unique=False)
        batch.create_index(
            'ix_score_run_equivalence',
            ['assessment_run_id', 'scoring_engine_version', 'scoring_configuration_hash',
             'surfer_profile_version', 'surfer_profile_hash', 'calculation_scope_hash'],
            unique=False,
        )

    with op.batch_alter_table('spot_score_snapshots') as batch:
        batch.add_column(sa.Column('assessment_point_id', sa.Integer(), nullable=True))
    bind.execute(sa.text("""
        UPDATE spot_score_snapshots
           SET assessment_point_id = (
               SELECT ap.id FROM spot_assessment_points AS ap
               JOIN spot_score_runs AS sr ON sr.assessment_run_id = ap.assessment_run_id
               WHERE sr.id = spot_score_snapshots.score_run_id
                 AND ap.spot_id = spot_score_snapshots.spot_id
                 AND ap.valid_at = spot_score_snapshots.valid_at
           )
         WHERE assessment_point_id IS NULL
    """))
    missing = _count(bind, 'SELECT COUNT(*) FROM spot_score_snapshots WHERE assessment_point_id IS NULL')
    if missing:
        raise RuntimeError('0008 defensive provenance assertion failed after successful preflight')
    with op.batch_alter_table('spot_score_snapshots') as batch:
        batch.alter_column('assessment_point_id', existing_type=sa.Integer(), nullable=False)
        batch.create_foreign_key(
            'fk_score_snapshot_assessment_point_id', 'spot_assessment_points',
            ['assessment_point_id'], ['id'], ondelete='RESTRICT',
        )
        batch.create_unique_constraint(
            'uq_score_snapshot_run_assessment_point', ['score_run_id', 'assessment_point_id']
        )
        for column in _SCORE_COLUMNS:
            batch.create_check_constraint(
                f'ck_score_snapshot_{column}_range',
                f'{column} IS NULL OR ({column} >= 0 AND {column} <= 100)',
            )
        batch.create_check_constraint(
            'ck_score_snapshot_penalty_range',
            'penalty_total IS NULL OR (penalty_total >= 0 AND penalty_total <= 100)',
        )
        batch.create_index('ix_spot_score_snapshots_run', ['score_run_id'], unique=False)
        batch.create_index('ix_spot_score_snapshots_assessment_point', ['assessment_point_id'], unique=False)
        batch.create_index('ix_spot_score_snapshots_spot_valid', ['spot_id', 'valid_at'], unique=False)


def _downgrade_preflight(bind) -> None:
    runs = sa.Table('spot_score_runs', sa.MetaData(), autoload_with=bind)
    identities: dict[tuple, int] = {}
    for run in bind.execute(sa.select(runs)).mappings():
        config_payload = run['scoring_configuration_json']
        profile_payload = run['surfer_profile_json']
        config_hash = (
            config_payload.get('legacy_hash')
            if isinstance(config_payload, dict)
            and isinstance(config_payload.get('legacy_hash'), str)
            else run['scoring_configuration_hash']
        )
        profile_hash = (
            profile_payload.get('legacy_hash')
            if isinstance(profile_payload, dict)
            and isinstance(profile_payload.get('legacy_hash'), str)
            else run['surfer_profile_hash']
        )
        identity = (
            run['assessment_run_id'], run['scoring_engine_version'], config_hash,
            run['surfer_profile_version'], profile_hash,
        )
        identities[identity] = identities.get(identity, 0) + 1
    collisions = sum(count > 1 for count in identities.values())
    if collisions:
        raise RuntimeError(
            f'0008 downgrade preflight found {collisions} identity collision group(s); '
            'remove duplicate scope/recalculation attempts before retrying'
        )


def downgrade():
    bind = op.get_bind()
    _downgrade_preflight(bind)

    with op.batch_alter_table('spot_score_snapshots') as batch:
        batch.drop_index('ix_spot_score_snapshots_spot_valid')
        batch.drop_index('ix_spot_score_snapshots_assessment_point')
        batch.drop_index('ix_spot_score_snapshots_run')
        batch.drop_constraint('ck_score_snapshot_penalty_range', type_='check')
        for column in reversed(_SCORE_COLUMNS):
            batch.drop_constraint(f'ck_score_snapshot_{column}_range', type_='check')
        batch.drop_constraint('uq_score_snapshot_run_assessment_point', type_='unique')
        batch.drop_constraint('fk_score_snapshot_assessment_point_id', type_='foreignkey')
        batch.drop_column('assessment_point_id')

    runs = sa.Table('spot_score_runs', sa.MetaData(), autoload_with=bind)
    for run in bind.execute(sa.select(runs)).mappings():
        config = run['scoring_configuration_json']
        profile = run['surfer_profile_json']
        values = {}
        if isinstance(config, dict) and isinstance(config.get('legacy_hash'), str):
            values['scoring_configuration_hash'] = config['legacy_hash']
        if isinstance(profile, dict) and isinstance(profile.get('legacy_hash'), str):
            values['surfer_profile_hash'] = profile['legacy_hash']
        if values:
            bind.execute(sa.update(runs).where(runs.c.id == run['id']).values(**values))

    with op.batch_alter_table('spot_score_runs') as batch:
        batch.drop_index('ix_score_run_equivalence')
        batch.drop_index('ix_spot_score_runs_status')
        batch.drop_index('ix_spot_score_runs_assessment_run_id')
        batch.drop_constraint('uq_score_run_input_scope_sequence', type_='unique')
        batch.drop_constraint('ck_score_run_sequence_nonnegative', type_='check')
        batch.drop_column('recalculation_sequence')
        batch.drop_column('calculation_scope_json')
        batch.drop_column('calculation_scope_hash')
        batch.drop_column('surfer_profile_json')
        batch.drop_column('surfer_profile_name')
        batch.drop_column('scoring_configuration_json')
        batch.alter_column(
            'surfer_profile_version', existing_type=sa.String(length=80),
            type_=sa.String(length=120), existing_nullable=False,
        )
        batch.alter_column(
            'scoring_engine_version', existing_type=sa.String(length=80),
            type_=sa.String(length=120), existing_nullable=False,
        )
        batch.create_unique_constraint(
            'uq_score_run_assessment_engine_config_profile',
            ['assessment_run_id', 'scoring_engine_version', 'scoring_configuration_hash',
             'surfer_profile_version', 'surfer_profile_hash'],
        )
