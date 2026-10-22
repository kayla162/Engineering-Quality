"""Add local users, tenants and revocable authentication sessions.

Revision ID: 0006
Revises: 0005
"""

from datetime import datetime, timezone
from typing import Sequence, Union
import uuid

from alembic import op
import sqlalchemy as sa

from app.core.config import settings


revision: str = "0006"
down_revision: Union[str, None] = "0005"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, None] = None


def upgrade() -> None:
    op.create_table(
        "tenants",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("name", sa.String(length=255), nullable=False),
        sa.Column("is_active", sa.Boolean(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.PrimaryKeyConstraint("id"),
    )

    default_tenant_id = uuid.UUID(settings.DEFAULT_TENANT_ID)
    tenants = sa.table(
        "tenants",
        sa.column("id", sa.Uuid()),
        sa.column("name", sa.String()),
        sa.column("is_active", sa.Boolean()),
        sa.column("created_at", sa.DateTime(timezone=True)),
    )
    op.get_bind().execute(
        tenants.insert().values(
            id=default_tenant_id,
            name="預設租戶",
            is_active=True,
            created_at=datetime.now(timezone.utc),
        )
    )

    bind = op.get_bind()
    for table_name in ("documents", "projects", "regulations"):
        bind.execute(
            sa.text(f"UPDATE {table_name} SET tenant_id = :tenant_id WHERE tenant_id IS NULL"),
            {"tenant_id": default_tenant_id},
        )

    op.create_table(
        "users",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("tenant_id", sa.Uuid(), nullable=False),
        sa.Column("username", sa.String(length=128), nullable=False),
        sa.Column("password_hash", sa.String(length=255), nullable=False),
        sa.Column("role", sa.String(length=32), nullable=False),
        sa.Column("is_active", sa.Boolean(), nullable=False),
        sa.Column("must_change_password", sa.Boolean(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["tenant_id"], ["tenants.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("username", name="uq_users_username"),
    )
    op.create_index("ix_users_tenant_id", "users", ["tenant_id"], unique=False)
    op.create_index("ix_users_tenant_role", "users", ["tenant_id", "role"], unique=False)

    op.create_table(
        "auth_sessions",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("user_id", sa.Uuid(), nullable=False),
        sa.Column("secret_hash", sa.String(length=64), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("revoked_at", sa.DateTime(timezone=True), nullable=True),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("secret_hash", name="uq_auth_sessions_secret_hash"),
    )
    op.create_index(
        "ix_auth_sessions_user_expiry", "auth_sessions", ["user_id", "expires_at"], unique=False
    )

    if bind.dialect.name == "sqlite":
        naming_convention = {"uq": "uq_%(table_name)s_%(column_0_name)s"}
        with op.batch_alter_table("documents", naming_convention=naming_convention) as batch:
            batch.drop_constraint("uq_documents_file_hash", type_="unique")
            batch.create_unique_constraint(
                "uq_documents_tenant_file_hash", ["tenant_id", "file_hash"]
            )
            batch.alter_column("tenant_id", existing_type=sa.Uuid(), nullable=False)
            batch.create_foreign_key(
                "fk_documents_tenant_id_tenants", "tenants", ["tenant_id"], ["id"], ondelete="RESTRICT"
            )
    else:
        # PostgreSQL names an unnamed UNIQUE constraint <table>_<column>_key.
        op.drop_constraint("documents_file_hash_key", "documents", type_="unique")
        with op.batch_alter_table("documents") as batch:
            batch.create_unique_constraint(
                "uq_documents_tenant_file_hash", ["tenant_id", "file_hash"]
            )
            batch.alter_column("tenant_id", existing_type=sa.Uuid(), nullable=False)
            batch.create_foreign_key(
                "fk_documents_tenant_id_tenants", "tenants", ["tenant_id"], ["id"], ondelete="RESTRICT"
            )

    with op.batch_alter_table("projects") as batch:
        batch.alter_column("tenant_id", existing_type=sa.Uuid(), nullable=False)
        batch.create_foreign_key(
            "fk_projects_tenant_id_tenants", "tenants", ["tenant_id"], ["id"], ondelete="RESTRICT"
        )

    with op.batch_alter_table("regulations") as batch:
        batch.alter_column("tenant_id", existing_type=sa.Uuid(), nullable=False)
        batch.create_foreign_key(
            "fk_regulations_tenant_id_tenants", "tenants", ["tenant_id"], ["id"], ondelete="RESTRICT"
        )


def downgrade() -> None:
    bind = op.get_bind()
    duplicate_hashes = bind.scalar(
        sa.text(
            "SELECT COUNT(*) FROM ("
            "SELECT file_hash FROM documents GROUP BY file_hash HAVING COUNT(*) > 1"
            ") AS duplicate_hashes"
        )
    )
    if duplicate_hashes:
        raise RuntimeError(
            "Cannot downgrade auth/tenant migration while different tenants share a file hash"
        )

    with op.batch_alter_table("regulations") as batch:
        batch.drop_constraint("fk_regulations_tenant_id_tenants", type_="foreignkey")
        batch.alter_column("tenant_id", existing_type=sa.Uuid(), nullable=True)

    with op.batch_alter_table("projects") as batch:
        batch.drop_constraint("fk_projects_tenant_id_tenants", type_="foreignkey")
        batch.alter_column("tenant_id", existing_type=sa.Uuid(), nullable=True)

    if bind.dialect.name == "sqlite":
        with op.batch_alter_table(
            "documents", naming_convention={"uq": "uq_%(table_name)s_%(column_0_name)s"}
        ) as batch:
            batch.drop_constraint("fk_documents_tenant_id_tenants", type_="foreignkey")
            batch.drop_constraint("uq_documents_tenant_file_hash", type_="unique")
            batch.create_unique_constraint("uq_documents_file_hash", ["file_hash"])
            batch.alter_column("tenant_id", existing_type=sa.Uuid(), nullable=True)
    else:
        op.drop_constraint("fk_documents_tenant_id_tenants", "documents", type_="foreignkey")
        op.drop_constraint("uq_documents_tenant_file_hash", "documents", type_="unique")
        op.create_unique_constraint("documents_file_hash_key", "documents", ["file_hash"])
        with op.batch_alter_table("documents") as batch:
            batch.alter_column("tenant_id", existing_type=sa.Uuid(), nullable=True)

    op.drop_index("ix_auth_sessions_user_expiry", table_name="auth_sessions")
    op.drop_table("auth_sessions")
    op.drop_index("ix_users_tenant_role", table_name="users")
    op.drop_index("ix_users_tenant_id", table_name="users")
    op.drop_table("users")
    op.drop_table("tenants")
