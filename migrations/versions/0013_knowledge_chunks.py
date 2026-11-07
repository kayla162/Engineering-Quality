"""knowledge_chunks: 語意搜尋的法規條文與規範章節（pgvector）

Revision ID: 0013
Revises: 0012
Create Date: 2026-11-07
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from pgvector.sqlalchemy import Vector

revision: str = '0013'
down_revision: Union[str, None] = '0012'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

DIMENSION = 1024


def upgrade() -> None:
    postgres = op.get_bind().dialect.name == 'postgresql'
    if postgres:
        op.execute('CREATE EXTENSION IF NOT EXISTS vector')

    op.create_table('knowledge_chunks',
    sa.Column('id', sa.Uuid(), nullable=False),
    sa.Column('ref', sa.String(length=128), nullable=False),
    sa.Column('kind', sa.String(length=24), nullable=False),
    sa.Column('source', sa.String(length=128), nullable=False),
    sa.Column('locator', sa.String(length=32), nullable=False),
    sa.Column('heading', sa.String(length=255), nullable=False),
    sa.Column('content', sa.Text(), nullable=False),
    sa.Column('embedding', Vector(DIMENSION) if postgres else sa.JSON(), nullable=True),
    sa.Column('embedding_model', sa.String(length=128), nullable=True),
    sa.Column('indexed_at', sa.DateTime(timezone=True), nullable=False),
    sa.PrimaryKeyConstraint('id'),
    sa.UniqueConstraint('ref')
    )
    if postgres:
        # 餘弦距離的 HNSW 索引。模型不知道這個索引（SQLite 沒有），migrations/env.py 讓 autogenerate 略過它
        op.execute(
            'CREATE INDEX ix_knowledge_chunks_embedding_hnsw ON knowledge_chunks '
            'USING hnsw (embedding vector_cosine_ops)'
        )


def downgrade() -> None:
    op.drop_table('knowledge_chunks')
