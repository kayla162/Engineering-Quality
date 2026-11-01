"""drawing_sheets and work_item_methods

Revision ID: 0011
Revises: 0010
Create Date: 2026-11-01
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

revision: str = '0011'
down_revision: Union[str, None] = '0010'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table('drawing_sheets',
    sa.Column('id', sa.Uuid(), nullable=False),
    sa.Column('document_id', sa.Uuid(), nullable=False),
    sa.Column('sheet_no', sa.String(length=16), nullable=False),
    sa.Column('title', sa.String(length=255), nullable=False),
    sa.Column('page', sa.Integer(), nullable=False),
    sa.Column('created_at', sa.DateTime(timezone=True), nullable=False),
    sa.ForeignKeyConstraint(['document_id'], ['documents.id'], ondelete='CASCADE'),
    sa.PrimaryKeyConstraint('id')
    )
    with op.batch_alter_table('drawing_sheets', schema=None) as batch_op:
        batch_op.create_index('ix_drawing_sheets_document', ['document_id'], unique=False)

    op.create_table('work_item_methods',
    sa.Column('id', sa.Uuid(), nullable=False),
    sa.Column('work_item_id', sa.Uuid(), nullable=False),
    sa.Column('options', sa.JSON().with_variant(postgresql.JSONB(astext_type=sa.Text()), 'postgresql'), nullable=False),
    sa.Column('selected', sa.String(length=64), nullable=True),
    sa.Column('evidence', sa.Text(), nullable=True),
    sa.Column('created_at', sa.DateTime(timezone=True), nullable=False),
    sa.ForeignKeyConstraint(['work_item_id'], ['work_items.id'], ondelete='CASCADE'),
    sa.PrimaryKeyConstraint('id')
    )
    with op.batch_alter_table('work_item_methods', schema=None) as batch_op:
        batch_op.create_index('ix_work_item_methods_work_item', ['work_item_id'], unique=False)



def downgrade() -> None:
    with op.batch_alter_table('work_item_methods', schema=None) as batch_op:
        batch_op.drop_index('ix_work_item_methods_work_item')

    op.drop_table('work_item_methods')
    with op.batch_alter_table('drawing_sheets', schema=None) as batch_op:
        batch_op.drop_index('ix_drawing_sheets_document')

    op.drop_table('drawing_sheets')
