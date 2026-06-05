"""Alembic 环境配置.

集成 SQLAlchemy 2.0 的 Base.metadata（从 backend.models.tables 导入），
并通过 backend.services.db 获取 SQLite 连接 URL。
"""
from logging.config import fileConfig

from sqlalchemy import engine_from_config, pool

from alembic import context

# 导入项目配置和元数据
from backend.services.db import DATABASE_URL
from backend.models.tables import Base


# Alembic Config 对象，提供 alembic.ini 中的值
config = context.config

# 动态注入 SQLite 数据库 URL（避免硬编码到 ini 文件）
config.set_main_option("sqlalchemy.url", DATABASE_URL)

# 解释 ini 文件的 logging 配置
if config.config_file_name is not None:
    fileConfig(config.config_file_name)

# 注入 SQLAlchemy 2.0 的 MetaData（用于 autogenerate）
target_metadata = Base.metadata


def run_migrations_offline() -> None:
    """在 offline 模式运行迁移（仅 URL，不需 Engine）."""
    url = config.get_main_option("sqlalchemy.url")
    context.configure(
        url=url,
        target_metadata=target_metadata,
        literal_binds=True,
        dialect_opts={"paramstyle": "named"},
    )

    with context.begin_transaction():
        context.run_migrations()


def run_migrations_online() -> None:
    """在 online 模式运行迁移（使用 Engine 和 DBAPI 连接）."""
    connectable = engine_from_config(
        config.get_section(config.config_ini_section, {}),
        prefix="sqlalchemy.",
        poolclass=pool.NullPool,
    )

    with connectable.connect() as connection:
        context.configure(
            connection=connection,
            target_metadata=target_metadata,
            render_as_batch=True,  # SQLite ALTER TABLE 兼容
        )

        with context.begin_transaction():
            context.run_migrations()


if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()
