"""harden append-only spot scoring foundation

Revision ID: 0008_spot_scoring_foundation
Revises: 0007_spot_assessment_force_runs
Create Date: 2026-07-13
"""
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


def upgrade():
    # Existing 0005 rows form attempt zero in an explicitly legacy scope. The
    # defaults are retained for old writers during a rolling application update.
    with op.batch_alter_table('spot_score_runs') as batch:
        batch.drop_constraint('uq_score_run_assessment_engine_config_profile', type_='unique')
        # Align persisted version widths with the ORM and public validator.
        # Length-enforcing databases fail closed rather than truncate legacy data.
        batch.alter_column(
            'scoring_engine_version', existing_type=sa.String(length=120),
            type_=sa.String(length=80), existing_nullable=False,
        )
        batch.alter_column(
            'surfer_profile_version', existing_type=sa.String(length=120),
            type_=sa.String(length=80), existing_nullable=False,
        )
        batch.add_column(sa.Column('calculation_scope_hash', sa.String(length=128), nullable=False, server_default='legacy-unscoped'))
        batch.add_column(sa.Column('recalculation_sequence', sa.Integer(), nullable=False, server_default='0'))
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

    # A score snapshot is provenance for exactly one typed assessment point.
    # Backfill pre-0008 rows from the already unique (run, spot, valid_at)
    # identities, and refuse to manufacture provenance when no match exists.
    with op.batch_alter_table('spot_score_snapshots') as batch:
        batch.add_column(sa.Column('assessment_point_id', sa.Integer(), nullable=True))
    bind = op.get_bind()
    bind.execute(sa.text("""
        UPDATE spot_score_snapshots
           SET assessment_point_id = (
               SELECT ap.id
                 FROM spot_assessment_points AS ap
                 JOIN spot_score_runs AS sr
                   ON sr.assessment_run_id = ap.assessment_run_id
                WHERE sr.id = spot_score_snapshots.score_run_id
                  AND ap.spot_id = spot_score_snapshots.spot_id
                  AND ap.valid_at = spot_score_snapshots.valid_at
           )
         WHERE assessment_point_id IS NULL
    """))
    missing = bind.execute(sa.text(
        'SELECT COUNT(*) FROM spot_score_snapshots WHERE assessment_point_id IS NULL'
    )).scalar_one()
    if missing:
        raise RuntimeError(
            f'0008 cannot infer assessment_point_id for {missing} legacy score snapshot(s); '
            'repair or remove those unverifiable rows before upgrading'
        )
    with op.batch_alter_table('spot_score_snapshots') as batch:
        batch.alter_column('assessment_point_id', existing_type=sa.Integer(), nullable=False)
        batch.create_foreign_key(
            'fk_score_snapshot_assessment_point_id', 'spot_assessment_points',
            ['assessment_point_id'], ['id'], ondelete='RESTRICT',
        )
        batch.create_unique_constraint(
            'uq_score_snapshot_run_assessment_point',
            ['score_run_id', 'assessment_point_id'],
        )
        for column in _SCORE_COLUMNS:
            batch.create_check_constraint(
                f'ck_score_snapshot_{column}_range',
                f'{column} IS NULL OR ({column} >= 0 AND {column} <= 100)',
            )
        batch.create_check_constraint(
            'ck_score_snapshot_penalty_nonnegative',
            'penalty_total IS NULL OR penalty_total >= 0',
        )
        batch.create_index('ix_spot_score_snapshots_run', ['score_run_id'], unique=False)
        batch.create_index('ix_spot_score_snapshots_assessment_point', ['assessment_point_id'], unique=False)
        batch.create_index('ix_spot_score_snapshots_spot_valid', ['spot_id', 'valid_at'], unique=False)


def downgrade():
    # Data-dependent: attempt sequences/scopes can coexist in 0008 but collide
    # under 0007's narrower score-run uniqueness. Operators must retain 0008 or
    # explicitly remove duplicate attempts before downgrading.
    with op.batch_alter_table('spot_score_snapshots') as batch:
        batch.drop_index('ix_spot_score_snapshots_spot_valid')
        batch.drop_index('ix_spot_score_snapshots_assessment_point')
        batch.drop_index('ix_spot_score_snapshots_run')
        batch.drop_constraint('ck_score_snapshot_penalty_nonnegative', type_='check')
        for column in reversed(_SCORE_COLUMNS):
            batch.drop_constraint(f'ck_score_snapshot_{column}_range', type_='check')
        batch.drop_constraint('uq_score_snapshot_run_assessment_point', type_='unique')
        batch.drop_constraint('fk_score_snapshot_assessment_point_id', type_='foreignkey')
        batch.drop_column('assessment_point_id')
    with op.batch_alter_table('spot_score_runs') as batch:
        batch.drop_index('ix_score_run_equivalence')
        batch.drop_index('ix_spot_score_runs_status')
        batch.drop_index('ix_spot_score_runs_assessment_run_id')
        batch.drop_constraint('uq_score_run_input_scope_sequence', type_='unique')
        batch.drop_constraint('ck_score_run_sequence_nonnegative', type_='check')
        batch.drop_column('recalculation_sequence')
        batch.drop_column('calculation_scope_hash')
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
