"""Alembic 環境設定。連線字串一律取自 app.core.config.settings，不寫死在 alembic.ini。"""

import asyncio
from logging.config import fileConfig

from alembic import context
from sqlalchemy.ext.asyncio import create_async_engine

from app.core.config import settings
from app.models import Base  # 匯入所有 model，autogenerate 才看得到

config = context.config
if config.config_file_name is not None:
    fileConfig(config.config_file_name)

target_metadata = Base.metadata


def run_migrations_offline() -> None:
    context.configure(
        url=settings.DATABASE_URL,
        target_metadata=target_metadata,
        literal_binds=True,
        dialect_opts={"paramstyle": "named"},
    )
    with context.begin_transaction():
        context.run_migrations()


#: 只在 PostgreSQL 建、模型裡沒有宣告的索引（0013 的 pgvector HNSW）。autogenerate 不要把它當成多出來的
_DATABASE_ONLY_INDEXES = {"ix_knowledge_chunks_embedding_hnsw"}


def _include_object(obj, name, type_, reflected, compare_to) -> bool:
    return not (type_ == "index" and name in _DATABASE_ONLY_INDEXES)


def _do_run_migrations(connection) -> None:
    context.configure(
        connection=connection,
        target_metadata=target_metadata,
        include_object=_include_object,
        render_as_batch=True,  # SQLite 需要 batch 模式才能改欄位
    )
    with context.begin_transaction():
        context.run_migrations()


async def run_migrations_online() -> None:
    engine = create_async_engine(settings.DATABASE_URL, future=True)
    async with engine.connect() as connection:
        await connection.run_sync(_do_run_migrations)
    await engine.dispose()


if context.is_offline_mode():
    run_migrations_offline()
else:
    asyncio.run(run_migrations_online())
