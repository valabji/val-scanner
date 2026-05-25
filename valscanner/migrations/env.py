from __future__ import annotations

import os
from logging.config import fileConfig

from alembic import context
from sqlalchemy import engine_from_config, pool

from valscanner.core.app_settings import active_url, mask_url
from valscanner.core.schema import metadata

config = context.config

# Only configure logging from alembic's ini file if we haven't already configured logging
# This preserves any custom logging setup from the CLI
if config.config_file_name and not __import__('logging').root.handlers:
    fileConfig(config.config_file_name)

# Resolution order: explicit -x url, $DATABASE_URL, active_url() from settings
explicit = config.get_main_option("sqlalchemy.url") or ""
if not explicit or explicit.startswith("sqlite:///valscanner.db"):
    # the ini default — treat as unset
    config.set_main_option(
        "sqlalchemy.url",
        os.environ.get("DATABASE_URL") or active_url(),
    )

# Surface the resolved URL safely (mask credentials)
print(f"alembic: target = {mask_url(config.get_main_option('sqlalchemy.url'))}")

target_metadata = metadata


def run_migrations_offline() -> None:
    url = config.get_main_option("sqlalchemy.url")
    context.configure(
        url=url,
        target_metadata=target_metadata,
        literal_binds=True,
        dialect_opts={"paramstyle": "named"},
        compare_type=True,
    )
    with context.begin_transaction():
        context.run_migrations()


def run_migrations_online() -> None:
    connectable = engine_from_config(
        config.get_section(config.config_ini_section, {}),
        prefix="sqlalchemy.",
        poolclass=pool.NullPool,
    )
    with connectable.connect() as connection:
        context.configure(
            connection=connection,
            target_metadata=target_metadata,
            compare_type=True,
        )
        with context.begin_transaction():
            context.run_migrations()


if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()
