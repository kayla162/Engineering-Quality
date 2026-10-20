"""圖說頁、圖項候選與人工覆核。"""
from alembic import op
import sqlalchemy as sa

revision = "0006"
down_revision = "0005"
branch_labels = None
depends_on = None


def upgrade():
    op.add_column("projects", sa.Column("drawing_revision", sa.Integer(), nullable=False, server_default="0"))
    op.create_table(
        "drawing_sheets",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column("project_id", sa.Uuid(), sa.ForeignKey("projects.id", ondelete="CASCADE"), nullable=False),
        sa.Column("document_id", sa.Uuid(), sa.ForeignKey("documents.id", ondelete="CASCADE"), nullable=False),
        sa.Column("page", sa.Integer(), nullable=False),
        sa.Column("number", sa.String(64)),
        sa.Column("title", sa.Text()),
        sa.Column("method", sa.String(16), nullable=False),
        sa.Column("evidence", sa.Text(), nullable=False),
        sa.Column("warning", sa.Text()),
        sa.UniqueConstraint("project_id", "document_id", "page", name="uq_drawing_page"),
    )
    op.create_index("ix_drawing_sheets_project_id", "drawing_sheets", ["project_id"])
    op.create_table(
        "drawing_items",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column("sheet_id", sa.Uuid(), sa.ForeignKey("drawing_sheets.id", ondelete="CASCADE"), nullable=False),
        sa.Column("name", sa.String(255), nullable=False),
        sa.Column("evidence", sa.Text(), nullable=False),
        sa.Column("review_status", sa.String(16), nullable=False),
        sa.Column("work_item_ids", sa.JSON(), nullable=False),
        sa.Column("review_fingerprint", sa.String(64)),
        sa.Column("review_note", sa.Text(), nullable=False),
    )
    op.create_index("ix_drawing_items_sheet_id", "drawing_items", ["sheet_id"])


def downgrade():
    op.drop_table("drawing_items")
    op.drop_table("drawing_sheets")
    with op.batch_alter_table("projects") as batch:
        batch.drop_column("drawing_revision")
