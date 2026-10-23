"""audit_log and regulation_changes

Revision ID: 0009
Revises: 0008
Create Date: 2026-10-24
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

revision: str = '0009'
down_revision: Union[str, None] = '0008'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table('audit_log',
    sa.Column('id', sa.Uuid(), nullable=False),
    sa.Column('tenant_id', sa.Uuid(), nullable=True),
    sa.Column('user_id', sa.Uuid(), nullable=True),
    sa.Column('username', sa.String(length=128), nullable=False),
    sa.Column('action', sa.String(length=64), nullable=False),
    sa.Column('resource_type', sa.String(length=32), nullable=True),
    sa.Column('resource_id', sa.String(length=64), nullable=True),
    sa.Column('detail', sa.JSON().with_variant(postgresql.JSONB(astext_type=sa.Text()), 'postgresql'), nullable=True),
    sa.Column('ip_address', sa.String(length=64), nullable=True),
    sa.Column('created_at', sa.DateTime(timezone=True), nullable=False),
    sa.ForeignKeyConstraint(['tenant_id'], ['tenants.id'], ondelete='CASCADE'),
    sa.ForeignKeyConstraint(['user_id'], ['users.id'], ondelete='SET NULL'),
    sa.PrimaryKeyConstraint('id')
    )
    with op.batch_alter_table('audit_log', schema=None) as batch_op:
        batch_op.create_index('ix_audit_log_action', ['action'], unique=False)
        batch_op.create_index('ix_audit_log_tenant_created', ['tenant_id', 'created_at'], unique=False)

    op.create_table('regulation_changes',
    sa.Column('id', sa.Uuid(), nullable=False),
    sa.Column('tenant_id', sa.Uuid(), nullable=False),
    sa.Column('regulation_id', sa.Uuid(), nullable=False),
    sa.Column('source', sa.String(length=64), nullable=False),
    sa.Column('changes', sa.JSON().with_variant(postgresql.JSONB(astext_type=sa.Text()), 'postgresql'), nullable=False),
    sa.Column('detected_at', sa.DateTime(timezone=True), nullable=False),
    sa.Column('acknowledged_at', sa.DateTime(timezone=True), nullable=True),
    sa.Column('acknowledged_by', sa.String(length=128), nullable=True),
    sa.ForeignKeyConstraint(['regulation_id'], ['regulations.id'], ondelete='CASCADE'),
    sa.ForeignKeyConstraint(['tenant_id'], ['tenants.id'], ondelete='CASCADE'),
    sa.PrimaryKeyConstraint('id')
    )
    with op.batch_alter_table('regulation_changes', schema=None) as batch_op:
        batch_op.create_index('ix_regulation_changes_tenant_open', ['tenant_id', 'acknowledged_at'], unique=False)



def downgrade() -> None:
    with op.batch_alter_table('regulation_changes', schema=None) as batch_op:
        batch_op.drop_index('ix_regulation_changes_tenant_open')

    op.drop_table('regulation_changes')
    with op.batch_alter_table('audit_log', schema=None) as batch_op:
        batch_op.drop_index('ix_audit_log_tenant_created')
        batch_op.drop_index('ix_audit_log_action')

    op.drop_table('audit_log')
