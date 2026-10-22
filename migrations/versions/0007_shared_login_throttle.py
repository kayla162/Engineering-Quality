"""Persist login throttle reservations across application workers.

Revision ID: 0007
Revises: 0006
"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "0007"
down_revision: Union[str, None] = "0006"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "auth_login_throttle_keys",
        sa.Column("identity_hash", sa.String(length=64), nullable=False),
        sa.Column("last_seen_at", sa.DateTime(timezone=True), nullable=False),
        sa.PrimaryKeyConstraint("identity_hash"),
    )
    op.create_index(
        "ix_auth_login_throttle_keys_last_seen",
        "auth_login_throttle_keys",
        ["last_seen_at"],
        unique=False,
    )
    op.create_table(
        "auth_login_attempts",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("identity_hash", sa.String(length=64), nullable=False),
        sa.Column("attempted_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(
            ["identity_hash"],
            ["auth_login_throttle_keys.identity_hash"],
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        "ix_auth_login_attempts_identity_time",
        "auth_login_attempts",
        ["identity_hash", "attempted_at"],
        unique=False,
    )
    op.create_index(
        "ix_auth_login_attempts_attempted_at",
        "auth_login_attempts",
        ["attempted_at"],
        unique=False,
    )


def downgrade() -> None:
    op.drop_index("ix_auth_login_attempts_attempted_at", table_name="auth_login_attempts")
    op.drop_index("ix_auth_login_attempts_identity_time", table_name="auth_login_attempts")
    op.drop_table("auth_login_attempts")
    op.drop_index(
        "ix_auth_login_throttle_keys_last_seen", table_name="auth_login_throttle_keys"
    )
    op.drop_table("auth_login_throttle_keys")
