"""interview rounds

Interviews can run in rounds (전형 차수: 1차 직무 면접, 2차 임원 면접 ...). Each posting gets an
ordered list of rounds; competency dictionary versions (and so their preset questions) belong to a
round, every session to one round, and people record a decision per application and round
(round_decisions, append-only revisions). check_points are the points a later round should check,
from interviewers or AI (with a verbatim quote). Preset questions can also belong to one session:
AI carry-over questions (이어 질문) built from earlier rounds' answers.

Existing data moves to round 1: every posting gets "1차 면접" (name 면접, position 1), its competency
sets and sessions go to it. interview_sessions.active_round_id repeats round_id while a session is
scheduled or in progress, so (application, active_round_id) is unique: never two open sessions of
one round for an application.

Downgrade keeps round 1 only: carry-over questions and the competency sets of later rounds (with
their preset questions) are deleted; sessions of later rounds stay, without a round.

Revision ID: 0006
Revises: 0005
Create Date: 2026-10-27 09:19:08.784429

"""
import uuid
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = '0006'
down_revision: Union[str, Sequence[str], None] = '0005'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

OPEN = "('scheduled', 'in_progress')"
FIRST_ROUND_NAME = '면접'


def upgrade() -> None:
    """Upgrade schema."""
    op.create_table('interview_rounds',
    sa.Column('posting_id', sa.String(length=36), nullable=False),
    sa.Column('position', sa.Integer(), nullable=False),
    sa.Column('name', sa.String(length=100), nullable=False),
    sa.Column('default_mode', sa.Enum('onsite', 'remote', name='sessionmode', native_enum=False, create_constraint=True, length=20), nullable=False),
    sa.Column('recommended_interviewers', sa.Integer(), nullable=False),
    sa.Column('show_previous_scores', sa.Boolean(), nullable=False),
    sa.Column('id', sa.String(length=36), nullable=False),
    sa.Column('created_at', sa.DateTime(timezone=True), nullable=False),
    sa.CheckConstraint("default_mode IN ('onsite', 'remote')", name='sessionmode'),
    sa.CheckConstraint("default_mode IN ('onsite', 'remote')", name=op.f('ck_interview_rounds_sessionmode')),
    sa.CheckConstraint('recommended_interviewers >= 1 AND recommended_interviewers <= 10', name=op.f('ck_interview_rounds_recommended_interviewers_range')),
    sa.ForeignKeyConstraint(['posting_id'], ['job_postings.id'], name=op.f('fk_interview_rounds_posting_id_job_postings'), ondelete='CASCADE'),
    sa.PrimaryKeyConstraint('id', name=op.f('pk_interview_rounds')),
    sa.UniqueConstraint('posting_id', 'position', name='uq_interview_rounds_posting_position')
    )
    op.create_table('check_points',
    sa.Column('session_id', sa.String(length=36), nullable=False),
    sa.Column('source', sa.Enum('interviewer', 'ai', name='checkpointsource', native_enum=False, create_constraint=True, length=20), nullable=False),
    sa.Column('competency', sa.String(length=100), nullable=True),
    sa.Column('text', sa.Text(), nullable=False),
    sa.Column('evidence', sa.Text(), nullable=True),
    sa.Column('qa_item_id', sa.String(length=36), nullable=True),
    sa.Column('author_id', sa.String(length=36), nullable=True),
    sa.Column('model', sa.String(length=100), nullable=True),
    sa.Column('prompt_version', sa.String(length=50), nullable=True),
    sa.Column('id', sa.String(length=36), nullable=False),
    sa.Column('created_at', sa.DateTime(timezone=True), nullable=False),
    sa.CheckConstraint("source <> 'ai' OR evidence IS NOT NULL", name=op.f('ck_check_points_ai_requires_evidence')),
    sa.CheckConstraint("source <> 'interviewer' OR author_id IS NOT NULL", name=op.f('ck_check_points_interviewer_requires_author')),
    sa.CheckConstraint("source IN ('interviewer', 'ai')", name='checkpointsource'),
    sa.CheckConstraint("source IN ('interviewer', 'ai')", name=op.f('ck_check_points_checkpointsource')),
    sa.ForeignKeyConstraint(['author_id'], ['interviewers.id'], name=op.f('fk_check_points_author_id_interviewers')),
    sa.ForeignKeyConstraint(['qa_item_id'], ['qa_items.id'], name=op.f('fk_check_points_qa_item_id_qa_items'), ondelete='SET NULL'),
    sa.ForeignKeyConstraint(['session_id'], ['interview_sessions.id'], name=op.f('fk_check_points_session_id_interview_sessions'), ondelete='CASCADE'),
    sa.PrimaryKeyConstraint('id', name=op.f('pk_check_points'))
    )
    with op.batch_alter_table('check_points', schema=None) as batch_op:
        batch_op.create_index(batch_op.f('ix_check_points_session_id'), ['session_id'], unique=False)

    op.create_table('round_decisions',
    sa.Column('application_id', sa.String(length=36), nullable=False),
    sa.Column('round_id', sa.String(length=36), nullable=False),
    sa.Column('session_id', sa.String(length=36), nullable=True),
    sa.Column('revision', sa.Integer(), nullable=False),
    sa.Column('decision', sa.Enum('passed', 'hold', 'rejected', name='decisionstatus', native_enum=False, create_constraint=True, length=20), nullable=False),
    sa.Column('reason', sa.Text(), nullable=False),
    sa.Column('decided_by', sa.String(length=36), nullable=False),
    sa.Column('id', sa.String(length=36), nullable=False),
    sa.Column('created_at', sa.DateTime(timezone=True), nullable=False),
    sa.CheckConstraint("decision IN ('passed', 'hold', 'rejected')", name='decisionstatus'),
    sa.CheckConstraint("decision IN ('passed', 'hold', 'rejected')", name=op.f('ck_round_decisions_decisionstatus')),
    sa.CheckConstraint('revision >= 1', name=op.f('ck_round_decisions_revision_positive')),
    sa.ForeignKeyConstraint(['application_id'], ['applications.id'], name=op.f('fk_round_decisions_application_id_applications'), ondelete='CASCADE'),
    sa.ForeignKeyConstraint(['decided_by'], ['interviewers.id'], name=op.f('fk_round_decisions_decided_by_interviewers')),
    sa.ForeignKeyConstraint(['round_id'], ['interview_rounds.id'], name=op.f('fk_round_decisions_round_id_interview_rounds')),
    sa.ForeignKeyConstraint(['session_id'], ['interview_sessions.id'], name=op.f('fk_round_decisions_session_id_interview_sessions'), ondelete='SET NULL'),
    sa.PrimaryKeyConstraint('id', name=op.f('pk_round_decisions')),
    sa.UniqueConstraint('application_id', 'round_id', 'revision', name='uq_round_decisions_revision')
    )
    with op.batch_alter_table('round_decisions', schema=None) as batch_op:
        batch_op.create_index(batch_op.f('ix_round_decisions_application_id'), ['application_id'], unique=False)

    # Every posting gets round 1, "1차 면접".
    conn = op.get_bind()
    postings = sa.table('job_postings', sa.column('id', sa.String), sa.column('created_at', sa.DateTime(timezone=True)))
    rounds = sa.table(
        'interview_rounds',
        sa.column('id', sa.String),
        sa.column('posting_id', sa.String),
        sa.column('position', sa.Integer),
        sa.column('name', sa.String),
        sa.column('default_mode', sa.String),
        sa.column('recommended_interviewers', sa.Integer),
        sa.column('show_previous_scores', sa.Boolean),
        sa.column('created_at', sa.DateTime(timezone=True)),
    )
    rows = [
        {
            'id': str(uuid.uuid4()),
            'posting_id': posting_id,
            'position': 1,
            'name': FIRST_ROUND_NAME,
            'default_mode': 'remote',
            'recommended_interviewers': 2,
            'show_previous_scores': False,
            'created_at': created_at,
        }
        for posting_id, created_at in conn.execute(sa.select(postings.c.id, postings.c.created_at))
    ]
    if rows:
        conn.execute(rounds.insert(), rows)
    first_round = "(SELECT r.id FROM interview_rounds r WHERE r.posting_id = {posting} AND r.position = 1)"

    with op.batch_alter_table('competency_sets', schema=None) as batch_op:
        batch_op.add_column(sa.Column('round_id', sa.String(length=36), nullable=True))
    conn.execute(sa.text(
        f"UPDATE competency_sets SET round_id = {first_round.format(posting='competency_sets.posting_id')}"
    ))
    with op.batch_alter_table('competency_sets', schema=None) as batch_op:
        batch_op.alter_column('round_id', existing_type=sa.String(length=36), nullable=False)
        batch_op.drop_constraint(batch_op.f('uq_competency_sets_posting_version'), type_='unique')
        batch_op.create_index(batch_op.f('ix_competency_sets_round_id'), ['round_id'], unique=False)
        batch_op.create_unique_constraint('uq_competency_sets_round_version', ['round_id', 'version'])
        batch_op.create_foreign_key(batch_op.f('fk_competency_sets_round_id_interview_rounds'), 'interview_rounds', ['round_id'], ['id'], ondelete='CASCADE')

    with op.batch_alter_table('interview_sessions', schema=None) as batch_op:
        batch_op.add_column(sa.Column('round_id', sa.String(length=36), nullable=True))
        batch_op.add_column(sa.Column('active_round_id', sa.String(length=36), nullable=True))
    posting_of_session = "(SELECT a.posting_id FROM applications a WHERE a.id = interview_sessions.application_id)"
    conn.execute(sa.text(
        f"UPDATE interview_sessions SET round_id = {first_round.format(posting=posting_of_session)}"
    ))
    # The newest open session of each application holds round 1 open (the API never let two be open).
    conn.execute(sa.text(
        f"UPDATE interview_sessions SET active_round_id = round_id WHERE status IN {OPEN} AND id = ("
        f"SELECT s2.id FROM interview_sessions s2 WHERE s2.application_id = interview_sessions.application_id "
        f"AND s2.status IN {OPEN} ORDER BY s2.created_at DESC, s2.id DESC LIMIT 1)"
    ))
    with op.batch_alter_table('interview_sessions', schema=None) as batch_op:
        batch_op.alter_column('round_id', existing_type=sa.String(length=36), nullable=False)
        batch_op.create_index(batch_op.f('ix_interview_sessions_round_id'), ['round_id'], unique=False)
        batch_op.create_unique_constraint('uq_interview_sessions_open_round', ['application_id', 'active_round_id'])
        batch_op.create_foreign_key(batch_op.f('fk_interview_sessions_round_id_interview_rounds'), 'interview_rounds', ['round_id'], ['id'])

    with op.batch_alter_table('preset_questions', schema=None) as batch_op:
        batch_op.add_column(sa.Column('session_id', sa.String(length=36), nullable=True))
        batch_op.add_column(sa.Column('based_on_qa_item_id', sa.String(length=36), nullable=True))
        batch_op.add_column(sa.Column('grounding', sa.Text(), nullable=True))
        batch_op.add_column(sa.Column('rationale', sa.Text(), nullable=True))
        batch_op.add_column(sa.Column('model', sa.String(length=100), nullable=True))
        batch_op.add_column(sa.Column('prompt_version', sa.String(length=50), nullable=True))
        batch_op.alter_column('competency_set_id',
               existing_type=sa.VARCHAR(length=36),
               nullable=True)
        batch_op.create_index(batch_op.f('ix_preset_questions_session_id'), ['session_id'], unique=False)
        batch_op.create_unique_constraint('uq_preset_questions_session_position', ['session_id', 'position'])
        batch_op.create_check_constraint('set_or_session', 'competency_set_id IS NOT NULL OR session_id IS NOT NULL')
        batch_op.create_foreign_key(batch_op.f('fk_preset_questions_session_id_interview_sessions'), 'interview_sessions', ['session_id'], ['id'], ondelete='CASCADE')


def downgrade() -> None:
    """Downgrade schema."""
    conn = op.get_bind()
    later_sets = (
        "SELECT cs.id FROM competency_sets cs JOIN interview_rounds r ON r.id = cs.round_id "
        "WHERE r.position > 1"
    )
    dropped_presets = f"SELECT id FROM preset_questions WHERE session_id IS NOT NULL OR competency_set_id IN ({later_sets})"
    for sql in (
        f"UPDATE qa_items SET preset_question_id = NULL WHERE preset_question_id IN ({dropped_presets})",
        f"DELETE FROM preset_questions WHERE id IN ({dropped_presets})",
        f"UPDATE interview_sessions SET competency_set_id = NULL WHERE competency_set_id IN ({later_sets})",
        f"DELETE FROM competency_sets WHERE id IN ({later_sets})",
    ):
        conn.execute(sa.text(sql))

    with op.batch_alter_table('preset_questions', schema=None) as batch_op:
        batch_op.drop_constraint(batch_op.f('fk_preset_questions_session_id_interview_sessions'), type_='foreignkey')
        batch_op.drop_constraint(batch_op.f('ck_preset_questions_set_or_session'), type_='check')
        batch_op.drop_constraint('uq_preset_questions_session_position', type_='unique')
        batch_op.drop_index(batch_op.f('ix_preset_questions_session_id'))
        batch_op.alter_column('competency_set_id',
               existing_type=sa.VARCHAR(length=36),
               nullable=False)
        batch_op.drop_column('prompt_version')
        batch_op.drop_column('model')
        batch_op.drop_column('rationale')
        batch_op.drop_column('grounding')
        batch_op.drop_column('based_on_qa_item_id')
        batch_op.drop_column('session_id')

    with op.batch_alter_table('interview_sessions', schema=None) as batch_op:
        batch_op.drop_constraint(batch_op.f('fk_interview_sessions_round_id_interview_rounds'), type_='foreignkey')
        batch_op.drop_constraint('uq_interview_sessions_open_round', type_='unique')
        batch_op.drop_index(batch_op.f('ix_interview_sessions_round_id'))
        batch_op.drop_column('active_round_id')
        batch_op.drop_column('round_id')

    with op.batch_alter_table('competency_sets', schema=None) as batch_op:
        batch_op.drop_constraint(batch_op.f('fk_competency_sets_round_id_interview_rounds'), type_='foreignkey')
        batch_op.drop_constraint('uq_competency_sets_round_version', type_='unique')
        batch_op.drop_index(batch_op.f('ix_competency_sets_round_id'))
        batch_op.create_unique_constraint(batch_op.f('uq_competency_sets_posting_version'), ['posting_id', 'version'])
        batch_op.drop_column('round_id')

    with op.batch_alter_table('round_decisions', schema=None) as batch_op:
        batch_op.drop_index(batch_op.f('ix_round_decisions_application_id'))

    op.drop_table('round_decisions')
    with op.batch_alter_table('check_points', schema=None) as batch_op:
        batch_op.drop_index(batch_op.f('ix_check_points_session_id'))

    op.drop_table('check_points')
    op.drop_table('interview_rounds')
