from __future__ import annotations

import asyncio
from logging.config import fileConfig
from typing import Any

from alembic import context
from api.config import config as app_config
from api.models.building import Building
from api.models.user import User
from sqlalchemy import pool
from sqlalchemy.engine import Connection
from sqlalchemy.ext.asyncio import async_engine_from_config
from sqlmodel import SQLModel

_model_imports = (Building, User)

config = context.config

if config.config_file_name is not None:
    fileConfig(config.config_file_name)

target_metadata = SQLModel.metadata
config.set_main_option("sqlalchemy.url", app_config.DB_URL.replace("%", "%%"))


def include_object(
    object_: Any,
    name: str | None,
    type_: str,
    reflected: bool,
    compare_to: Any,
) -> bool:
    """Exclude tables owned by Prefect from HUD migration autogeneration."""

    del object_, name, type_
    return not (reflected and compare_to is None)


def configure_context(**kwargs: Any) -> None:
    context.configure(
        target_metadata=target_metadata,
        version_table="hud_alembic_version",
        include_object=include_object,
        **kwargs,
    )


def run_migrations_offline() -> None:
    configure_context(
        url=config.get_main_option("sqlalchemy.url"),
        literal_binds=True,
        dialect_opts={"paramstyle": "named"},
    )

    with context.begin_transaction():
        context.run_migrations()


def do_run_migrations(connection: Connection) -> None:
    configure_context(connection=connection)
    with context.begin_transaction():
        context.run_migrations()


async def run_async_migrations() -> None:
    connectable = async_engine_from_config(
        config.get_section(config.config_ini_section, {}),
        prefix="sqlalchemy.",
        poolclass=pool.NullPool,
    )

    async with connectable.connect() as connection:
        await connection.run_sync(do_run_migrations)

    await connectable.dispose()


def run_migrations_online() -> None:
    asyncio.run(run_async_migrations())


if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()
