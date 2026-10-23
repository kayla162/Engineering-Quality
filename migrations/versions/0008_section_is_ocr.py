"""document_sections.is_ocr: mark paragraphs that came from OCR.

Revision ID: 0008
Revises: 0007
"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "0008"
down_revision: Union[str, None] = "0007"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    with op.batch_alter_table("document_sections", schema=None) as batch_op:
        batch_op.add_column(
            sa.Column("is_ocr", sa.Boolean(), nullable=False, server_default=sa.false())
        )


def downgrade() -> None:
    with op.batch_alter_table("document_sections", schema=None) as batch_op:
        batch_op.drop_column("is_ocr")
