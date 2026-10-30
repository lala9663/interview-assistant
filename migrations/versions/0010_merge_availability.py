"""merge availability

One interviewer's availability blocks may no longer touch or overlap: the API now merges a block
into the ones it touches when it is created or moved (api/routes/schedule.py). Rows entered
before that, one hour per click, could sit on top of each other; this joins each run of touching
rows into its earliest row and deletes the rest. No schema change, and nothing to undo: the
merged rows cover exactly the same time.

Revision ID: 0010
Revises: 0009
Create Date: 2026-10-30 16:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = '0010'
down_revision: Union[str, Sequence[str], None] = '0009'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

_availabilities = sa.table(
    'availabilities',
    sa.column('id', sa.String),
    sa.column('interviewer_id', sa.String),
    sa.column('start_at', sa.DateTime(timezone=True)),
    sa.column('end_at', sa.DateTime(timezone=True)),
    sa.column('created_at', sa.DateTime(timezone=True)),
)


def upgrade() -> None:
    """Upgrade schema."""
    t = _availabilities
    conn = op.get_bind()
    rows = conn.execute(
        sa.select(t.c.id, t.c.interviewer_id, t.c.start_at, t.c.end_at).order_by(
            t.c.interviewer_id, t.c.start_at, t.c.created_at
        )
    ).all()
    head = None  # [id, interviewer_id, start_at, end_at, changed]
    for id_, interviewer_id, start_at, end_at in rows:
        if head and head[1] == interviewer_id and start_at <= head[3]:
            if end_at > head[3]:
                head[3], head[4] = end_at, True
            conn.execute(sa.delete(t).where(t.c.id == id_))
            continue
        _save(conn, head)
        head = [id_, interviewer_id, start_at, end_at, False]
    _save(conn, head)


def _save(conn, head) -> None:
    if head and head[4]:
        conn.execute(sa.update(_availabilities).where(_availabilities.c.id == head[0]).values(end_at=head[3]))


def downgrade() -> None:
    """Downgrade schema."""
