"""permit append-only forced spot assessment reruns

Revision ID: 0007_spot_assessment_force_runs
Revises: 0006_consensus_fields
Create Date: 2026-07-13
"""
import sqlalchemy as sa
from alembic import op

revision = '0007_spot_assessment_force_runs'
down_revision = '0006_consensus_fields'
branch_labels = None
depends_on = None


def upgrade():
    # The 0005 uniqueness blocked explicitly forced, append-only reruns. Keep
    # sequence zero unique for the ordinary idempotent run and allocate positive
    # sequences only for explicit force requests.
    with op.batch_alter_table('spot_assessment_runs') as batch:
        batch.drop_constraint('uq_assessment_run_consensus_rules_engine', type_='unique')
        batch.add_column(sa.Column('calculation_scope_hash', sa.String(length=128), nullable=False, server_default='legacy-unscoped'))
        batch.add_column(sa.Column('recalculation_sequence', sa.Integer(), nullable=False, server_default='0'))
        batch.create_unique_constraint(
            'uq_assessment_run_input_scope_sequence',
            ['consensus_run_id', 'spot_rules_hash', 'spot_intelligence_engine_version', 'configuration_hash', 'calculation_scope_hash', 'recalculation_sequence'],
        )
        batch.create_index(
            'ix_assessment_run_equivalence',
            ['consensus_run_id', 'spot_rules_hash', 'spot_intelligence_engine_version', 'configuration_hash'],
            unique=False,
        )
        # 0005 omitted these ORM-declared indexes.
        batch.create_index('ix_spot_assessment_runs_consensus_run_id', ['consensus_run_id'], unique=False)
        batch.create_index('ix_spot_assessment_runs_status', ['status'], unique=False)


def downgrade():
    # Data-dependent after forced reruns: the old schema cannot represent two
    # otherwise equivalent immutable rows. Operators must retain 0007 or resolve
    # such rows explicitly before downgrading.
    with op.batch_alter_table('spot_assessment_runs') as batch:
        batch.drop_index('ix_spot_assessment_runs_status')
        batch.drop_index('ix_spot_assessment_runs_consensus_run_id')
        batch.drop_index('ix_assessment_run_equivalence')
        batch.drop_constraint('uq_assessment_run_input_scope_sequence', type_='unique')
        batch.drop_column('recalculation_sequence')
        batch.drop_column('calculation_scope_hash')
        batch.create_unique_constraint(
            'uq_assessment_run_consensus_rules_engine',
            ['consensus_run_id', 'spot_rules_hash', 'spot_intelligence_engine_version', 'configuration_hash'],
        )
