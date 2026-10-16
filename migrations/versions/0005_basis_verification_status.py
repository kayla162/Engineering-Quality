"""basis_verification_status

加 work_item_bases.verification_status。既有的列不回填：NULL 就是「未查證」，
和這個欄位平常的語意一致，重建檢核表時才會補上。

Revision ID: 0005
Revises: 0004
Create Date: 2026-10-16
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = '0005'
down_revision: Union[str, None] = '0004'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    with op.batch_alter_table('work_item_bases', schema=None) as batch_op:
        batch_op.add_column(sa.Column('verification_status', sa.String(length=32), nullable=True))


def downgrade() -> None:
    with op.batch_alter_table('work_item_bases', schema=None) as batch_op:
        batch_op.drop_column('verification_status')
