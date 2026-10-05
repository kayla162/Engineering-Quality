"""document_parse_quality

Revision ID: 0003
Revises: 0002
Create Date: 2026-10-05
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = '0003'
down_revision: Union[str, None] = '0002'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    with op.batch_alter_table('documents', schema=None) as batch_op:
        batch_op.add_column(
            sa.Column(
                'parse_quality', sa.String(length=16), nullable=False, server_default='OK'
            )
        )
        batch_op.add_column(sa.Column('parse_quality_note', sa.String(length=255), nullable=True))


def downgrade() -> None:
    with op.batch_alter_table('documents', schema=None) as batch_op:
        batch_op.drop_column('parse_quality_note')
        batch_op.drop_column('parse_quality')
