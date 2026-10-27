"""question bank and retrieval

The question bank (question_bank_items: vetted questions per job family, competency and optional
round, with good follow-up examples, draft/approved/retired, prohibited-question flags) and the
rubric anchors (rubric_examples: made-up answers people wrote and approved for each score 1-5 of
a competency). Embedding vectors are stored engine-independently (float32 bytes + a JSON map of
sparse weights) with the key of the model that made them (embedding_vectors), and the state of each
model's index (embedding_indexes: building, ready, failed, progress) so a new model's index is
built while the old one keeps serving. A CHECK keeps the vector store to company-written text.

follow_up_suggestions gains where a suggestion came from (source bank/ai, the bank question, its
retrieval score), how long after the request it appeared, and whether it was dropped as a
duplicate of a question already asked (discarded, duplicate_of, similarity). Existing rows are AI.

Revision ID: 0007
Revises: 0006
Create Date: 2026-10-27 11:16:11.391305

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = '0007'
down_revision: Union[str, Sequence[str], None] = '0006'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    op.create_table('embedding_indexes',
    sa.Column('index_key', sa.String(length=120), nullable=False),
    sa.Column('model', sa.String(length=100), nullable=False),
    sa.Column('dimensions', sa.Integer(), nullable=False),
    sa.Column('spec', sa.JSON(), nullable=False),
    sa.Column('status', sa.Enum('building', 'ready', 'failed', name='indexstatus', native_enum=False, create_constraint=True, length=20), nullable=False),
    sa.Column('total', sa.Integer(), nullable=False),
    sa.Column('done', sa.Integer(), nullable=False),
    sa.Column('started_at', sa.DateTime(timezone=True), nullable=False),
    sa.Column('finished_at', sa.DateTime(timezone=True), nullable=True),
    sa.Column('error', sa.Text(), nullable=True),
    sa.CheckConstraint("status IN ('building', 'ready', 'failed')", name='indexstatus'),
    sa.CheckConstraint("status IN ('building', 'ready', 'failed')", name=op.f('ck_embedding_indexes_indexstatus')),
    sa.PrimaryKeyConstraint('index_key', name=op.f('pk_embedding_indexes'))
    )
    op.create_table('embedding_vectors',
    sa.Column('index_key', sa.String(length=120), nullable=False),
    sa.Column('owner_type', sa.String(length=30), nullable=False),
    sa.Column('owner_id', sa.String(length=36), nullable=False),
    sa.Column('part', sa.Integer(), nullable=False),
    sa.Column('text_hash', sa.String(length=64), nullable=False),
    sa.Column('dimensions', sa.Integer(), nullable=False),
    sa.Column('dense', sa.LargeBinary(), nullable=False),
    sa.Column('sparse', sa.JSON(), nullable=True),
    sa.Column('created_at', sa.DateTime(timezone=True), nullable=False),
    sa.Column('id', sa.String(length=36), nullable=False),
    sa.CheckConstraint("owner_type IN ('question', 'rubric', 'competency_set')", name=op.f('ck_embedding_vectors_company_text_only')),
    sa.PrimaryKeyConstraint('id', name=op.f('pk_embedding_vectors')),
    sa.UniqueConstraint('index_key', 'owner_type', 'owner_id', 'part', name='uq_embedding_vectors_owner')
    )
    with op.batch_alter_table('embedding_vectors', schema=None) as batch_op:
        batch_op.create_index(batch_op.f('ix_embedding_vectors_index_key'), ['index_key'], unique=False)

    op.create_table('question_bank_items',
    sa.Column('job_family', sa.String(length=100), nullable=False),
    sa.Column('competency', sa.String(length=100), nullable=False),
    sa.Column('round_position', sa.Integer(), nullable=True),
    sa.Column('question', sa.Text(), nullable=False),
    sa.Column('intent', sa.String(length=200), nullable=False),
    sa.Column('follow_ups', sa.JSON(), nullable=False),
    sa.Column('status', sa.Enum('draft', 'approved', 'retired', name='bankstatus', native_enum=False, create_constraint=True, length=20), nullable=False),
    sa.Column('flags', sa.JSON(), nullable=False),
    sa.Column('source', sa.Enum('manual', 'csv', 'seed', name='banksource', native_enum=False, create_constraint=True, length=20), nullable=False),
    sa.Column('created_by', sa.String(length=36), nullable=False),
    sa.Column('updated_at', sa.DateTime(timezone=True), nullable=False),
    sa.Column('approved_by', sa.String(length=36), nullable=True),
    sa.Column('approved_at', sa.DateTime(timezone=True), nullable=True),
    sa.Column('retired_at', sa.DateTime(timezone=True), nullable=True),
    sa.Column('id', sa.String(length=36), nullable=False),
    sa.Column('created_at', sa.DateTime(timezone=True), nullable=False),
    sa.CheckConstraint("source IN ('manual', 'csv', 'seed')", name='banksource'),
    sa.CheckConstraint("source IN ('manual', 'csv', 'seed')", name=op.f('ck_question_bank_items_banksource')),
    sa.CheckConstraint("status <> 'approved' OR approved_by IS NOT NULL", name=op.f('ck_question_bank_items_approved_has_approver')),
    sa.CheckConstraint("status IN ('draft', 'approved', 'retired')", name='bankstatus'),
    sa.CheckConstraint("status IN ('draft', 'approved', 'retired')", name=op.f('ck_question_bank_items_bankstatus')),
    sa.CheckConstraint('round_position IS NULL OR (round_position >= 1 AND round_position <= 6)', name=op.f('ck_question_bank_items_round_position_range')),
    sa.ForeignKeyConstraint(['approved_by'], ['interviewers.id'], name=op.f('fk_question_bank_items_approved_by_interviewers')),
    sa.ForeignKeyConstraint(['created_by'], ['interviewers.id'], name=op.f('fk_question_bank_items_created_by_interviewers')),
    sa.PrimaryKeyConstraint('id', name=op.f('pk_question_bank_items'))
    )
    with op.batch_alter_table('question_bank_items', schema=None) as batch_op:
        batch_op.create_index(batch_op.f('ix_question_bank_items_job_family'), ['job_family'], unique=False)

    op.create_table('rubric_examples',
    sa.Column('job_family', sa.String(length=100), nullable=False),
    sa.Column('competency', sa.String(length=100), nullable=False),
    sa.Column('score', sa.Integer(), nullable=False),
    sa.Column('question', sa.Text(), nullable=False),
    sa.Column('answer', sa.Text(), nullable=False),
    sa.Column('rationale', sa.Text(), nullable=False),
    sa.Column('status', sa.Enum('draft', 'approved', 'retired', name='bankstatus', native_enum=False, create_constraint=True, length=20), nullable=False),
    sa.Column('source', sa.Enum('manual', 'csv', 'seed', name='banksource', native_enum=False, create_constraint=True, length=20), nullable=False),
    sa.Column('created_by', sa.String(length=36), nullable=False),
    sa.Column('updated_at', sa.DateTime(timezone=True), nullable=False),
    sa.Column('approved_by', sa.String(length=36), nullable=True),
    sa.Column('approved_at', sa.DateTime(timezone=True), nullable=True),
    sa.Column('retired_at', sa.DateTime(timezone=True), nullable=True),
    sa.Column('id', sa.String(length=36), nullable=False),
    sa.Column('created_at', sa.DateTime(timezone=True), nullable=False),
    sa.CheckConstraint("source IN ('manual', 'csv', 'seed')", name='banksource'),
    sa.CheckConstraint("source IN ('manual', 'csv', 'seed')", name=op.f('ck_rubric_examples_banksource')),
    sa.CheckConstraint("status <> 'approved' OR approved_by IS NOT NULL", name=op.f('ck_rubric_examples_approved_has_approver')),
    sa.CheckConstraint("status IN ('draft', 'approved', 'retired')", name='bankstatus'),
    sa.CheckConstraint("status IN ('draft', 'approved', 'retired')", name=op.f('ck_rubric_examples_bankstatus')),
    sa.CheckConstraint('score >= 1 AND score <= 5', name=op.f('ck_rubric_examples_score_range')),
    sa.ForeignKeyConstraint(['approved_by'], ['interviewers.id'], name=op.f('fk_rubric_examples_approved_by_interviewers')),
    sa.ForeignKeyConstraint(['created_by'], ['interviewers.id'], name=op.f('fk_rubric_examples_created_by_interviewers')),
    sa.PrimaryKeyConstraint('id', name=op.f('pk_rubric_examples'))
    )
    with op.batch_alter_table('rubric_examples', schema=None) as batch_op:
        batch_op.create_index(batch_op.f('ix_rubric_examples_job_family'), ['job_family'], unique=False)

    with op.batch_alter_table('follow_up_suggestions', schema=None) as batch_op:
        batch_op.add_column(sa.Column('source', sa.Enum('bank', 'ai', name='suggestionsource', native_enum=False, create_constraint=True, length=20), server_default='ai', nullable=False))
        batch_op.add_column(sa.Column('bank_item_id', sa.String(length=36), nullable=True))
        batch_op.add_column(sa.Column('retrieval_score', sa.Float(), nullable=True))
        batch_op.add_column(sa.Column('latency_ms', sa.Integer(), nullable=True))
        batch_op.add_column(sa.Column('discarded', sa.String(length=20), nullable=True))
        batch_op.add_column(sa.Column('duplicate_of', sa.Text(), nullable=True))
        batch_op.add_column(sa.Column('similarity', sa.Float(), nullable=True))
        batch_op.create_foreign_key(batch_op.f('fk_follow_up_suggestions_bank_item_id_question_bank_items'), 'question_bank_items', ['bank_item_id'], ['id'], ondelete='SET NULL')



def downgrade() -> None:
    """Downgrade schema."""
    with op.batch_alter_table('follow_up_suggestions', schema=None) as batch_op:
        batch_op.drop_constraint(batch_op.f('fk_follow_up_suggestions_bank_item_id_question_bank_items'), type_='foreignkey')
        batch_op.drop_constraint(batch_op.f('ck_follow_up_suggestions_suggestionsource'), type_='check')
        batch_op.drop_column('similarity')
        batch_op.drop_column('duplicate_of')
        batch_op.drop_column('discarded')
        batch_op.drop_column('latency_ms')
        batch_op.drop_column('retrieval_score')
        batch_op.drop_column('bank_item_id')
        batch_op.drop_column('source')

    with op.batch_alter_table('rubric_examples', schema=None) as batch_op:
        batch_op.drop_index(batch_op.f('ix_rubric_examples_job_family'))

    op.drop_table('rubric_examples')
    with op.batch_alter_table('question_bank_items', schema=None) as batch_op:
        batch_op.drop_index(batch_op.f('ix_question_bank_items_job_family'))

    op.drop_table('question_bank_items')
    with op.batch_alter_table('embedding_vectors', schema=None) as batch_op:
        batch_op.drop_index(batch_op.f('ix_embedding_vectors_index_key'))

    op.drop_table('embedding_vectors')
    op.drop_table('embedding_indexes')
