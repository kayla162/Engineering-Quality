"""enterprise_documents

Revision ID: 0010
Revises: 0009
Create Date: 2026-11-01
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

revision: str = '0010'
down_revision: Union[str, None] = '0009'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table('enterprise_documents',
    sa.Column('id', sa.Uuid(), nullable=False),
    sa.Column('tenant_id', sa.Uuid(), nullable=False),
    sa.Column('doc_number', sa.String(length=64), nullable=False),
    sa.Column('name', sa.String(length=255), nullable=False),
    sa.Column('doc_type', sa.String(length=32), nullable=False),
    sa.Column('revision', sa.String(length=32), nullable=False),
    sa.Column('effective_date', sa.Date(), nullable=False),
    sa.Column('last_revised_date', sa.Date(), nullable=True),
    sa.Column('status', sa.String(length=24), nullable=False),
    sa.Column('replaced_by', sa.String(length=64), nullable=True),
    sa.Column('owner', sa.String(length=128), nullable=True),
    sa.Column('aliases', sa.JSON().with_variant(postgresql.JSONB(astext_type=sa.Text()), 'postgresql'), nullable=False),
    sa.Column('note', sa.String(length=255), nullable=True),
    sa.Column('imported_at', sa.DateTime(timezone=True), nullable=False),
    sa.Column('imported_by', sa.String(length=128), nullable=False),
    sa.ForeignKeyConstraint(['tenant_id'], ['tenants.id'], ondelete='CASCADE'),
    sa.PrimaryKeyConstraint('id'),
    sa.UniqueConstraint('tenant_id', 'doc_number', name='uq_enterprise_documents_number')
    )
    with op.batch_alter_table('enterprise_documents', schema=None) as batch_op:
        batch_op.create_index('ix_enterprise_documents_tenant', ['tenant_id'], unique=False)



def downgrade() -> None:
    with op.batch_alter_table('enterprise_documents', schema=None) as batch_op:
        batch_op.drop_index('ix_enterprise_documents_tenant')

    op.drop_table('enterprise_documents')
