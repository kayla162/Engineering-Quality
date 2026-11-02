"""drawing_sheets.is_ocr and work_item_contract_refs

Revision ID: 0012
Revises: 0011
Create Date: 2026-11-02
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

revision: str = '0012'
down_revision: Union[str, None] = '0011'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    with op.batch_alter_table('drawing_sheets', schema=None) as batch_op:
        batch_op.add_column(sa.Column('is_ocr', sa.Boolean(), nullable=False, server_default=sa.false()))

    op.create_table('work_item_contract_refs',
    sa.Column('id', sa.Uuid(), nullable=False),
    sa.Column('work_item_id', sa.Uuid(), nullable=False),
    sa.Column('page', sa.Integer(), nullable=True),
    sa.Column('heading', sa.String(length=64), nullable=True),
    sa.Column('excerpt', sa.Text(), nullable=False),
    sa.Column('keyword', sa.String(length=64), nullable=False),
    sa.Column('created_at', sa.DateTime(timezone=True), nullable=False),
    sa.ForeignKeyConstraint(['work_item_id'], ['work_items.id'], ondelete='CASCADE'),
    sa.PrimaryKeyConstraint('id')
    )
    with op.batch_alter_table('work_item_contract_refs', schema=None) as batch_op:
        batch_op.create_index('ix_work_item_contract_refs_work_item', ['work_item_id'], unique=False)


def downgrade() -> None:
    with op.batch_alter_table('work_item_contract_refs', schema=None) as batch_op:
        batch_op.drop_index('ix_work_item_contract_refs_work_item')
    op.drop_table('work_item_contract_refs')
    with op.batch_alter_table('drawing_sheets', schema=None) as batch_op:
        batch_op.drop_column('is_ocr')
