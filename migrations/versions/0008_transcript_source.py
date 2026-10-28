"""transcript source

transcript_segments gains `source`: `live` for what the streaming STT wrote during the interview
(every existing row), `batch` for the recording transcribed again after the interview by the
STT 사후 model when admin > 모델 설정 asks for it (docs/audio-input.md 8장).

Revision ID: 0008
Revises: 0007
Create Date: 2026-10-28 19:30:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = '0008'
down_revision: Union[str, Sequence[str], None] = '0007'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    with op.batch_alter_table('transcript_segments', schema=None) as batch_op:
        batch_op.add_column(sa.Column('source', sa.String(length=10), server_default='live', nullable=False))


def downgrade() -> None:
    """Downgrade schema."""
    with op.batch_alter_table('transcript_segments', schema=None) as batch_op:
        batch_op.drop_column('source')
