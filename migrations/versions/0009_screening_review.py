"""screening review

screenings gains the structured assessment (screening-v0.5: per JD requirement a verdict, short
evidence and where in the document it is; points to check in the interview), the AI
recommendation as its own column and the reason a person gave for 탈락. Rows screened before
v0.5 keep their free-text rationale; their recommendation is read from the rationale's first
line, which ended with "(AI 권고: 통과|보류|탈락)".

session_interviewers gains `ai_revealed_at`: when an interviewer chose to see the AI scores
before submitting their own (they are hidden from them until then).

Revision ID: 0009
Revises: 0008
Create Date: 2026-10-30 10:00:00.000000

"""
import re
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = '0009'
down_revision: Union[str, Sequence[str], None] = '0008'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

_LABEL = {'통과': 'passed', '보류': 'hold', '탈락': 'rejected'}


def upgrade() -> None:
    """Upgrade schema."""
    with op.batch_alter_table('screenings', schema=None) as batch_op:
        batch_op.add_column(sa.Column('recommendation', sa.String(length=16), nullable=True))
        batch_op.add_column(sa.Column('assessment', sa.JSON(), nullable=True))
        batch_op.add_column(sa.Column('reject_reason', sa.Text(), nullable=True))
    with op.batch_alter_table('session_interviewers', schema=None) as batch_op:
        batch_op.add_column(sa.Column('ai_revealed_at', sa.DateTime(timezone=True), nullable=True))

    conn = op.get_bind()
    for id_, rationale in conn.execute(sa.text('SELECT id, rationale FROM screenings')).all():
        m = re.search(r'\(AI 권고: ([^)]+)\)', (rationale or '').split('\n', 1)[0])
        if m and m.group(1).strip() in _LABEL:
            conn.execute(
                sa.text('UPDATE screenings SET recommendation = :r WHERE id = :id'),
                {'r': _LABEL[m.group(1).strip()], 'id': id_},
            )


def downgrade() -> None:
    """Downgrade schema."""
    with op.batch_alter_table('session_interviewers', schema=None) as batch_op:
        batch_op.drop_column('ai_revealed_at')
    with op.batch_alter_table('screenings', schema=None) as batch_op:
        batch_op.drop_column('reject_reason')
        batch_op.drop_column('assessment')
        batch_op.drop_column('recommendation')
