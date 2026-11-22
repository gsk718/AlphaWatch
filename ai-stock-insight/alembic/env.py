from logging.config import fileConfig
import os
from pathlib import Path
import sys

from sqlalchemy import engine_from_config
from sqlalchemy import pool

from alembic import context

# this is the Alembic Config object, which provides
# access to the values within the .ini file in use.
config = context.config

# Interpret the config file for Python logging.
# This line sets up loggers basically.
if config.config_file_name is not None:
    fileConfig(config.config_file_name)

# The project root is the directory containing this file's parent.
project_root = Path(__file__).resolve().parents[1]
if str(project_root) not in sys.path:
    sys.path.insert(0, str(project_root))

# Import models directly so loading Alembic does not initialize the application
# engine before an opted-in test URL has been validated.
from database.base import Base  # noqa: E402
from database.models import BacktestResult, StockAnalysis  # noqa: E402,F401

target_metadata = Base.metadata
if os.getenv("RUN_POSTGRES_TESTS") == "1":
    # Keep the validator shared with pytest, without importing its fixtures.
    tests_root = project_root.parent / "tests"
    if str(tests_root) not in sys.path:
        sys.path.insert(0, str(tests_root))
    from integration.postgres_config import validate_test_database_url  # noqa: E402

    migration_url = validate_test_database_url(os.getenv("TEST_DATABASE_URL"))
else:
    from database.session import DATABASE_URL  # noqa: E402

    migration_url = DATABASE_URL

config.set_main_option("sqlalchemy.url", str(migration_url).replace("%", "%%"))

# other values from the config, defined by the needs of env.py,
# can be acquired:
# my_important_option = config.get_main_option("my_important_option")
# ... etc.


def run_migrations_offline() -> None:
    """Run migrations in 'offline' mode.

    This configures the context with just a URL
    and not an Engine, though an Engine is acceptable
    here as well.  By skipping the Engine creation
    we don't even need a DBAPI to be available.

    Calls to context.execute() here emit the given string to the
    script output.

    """
    url = config.get_main_option("sqlalchemy.url")
    context.configure(
        url=url,
        target_metadata=target_metadata,
        literal_binds=True,
        dialect_opts={"paramstyle": "named"},
        compare_type=True,
        compare_server_default=True,
    )

    with context.begin_transaction():
        context.run_migrations()


def run_migrations_online() -> None:
    """Run migrations in 'online' mode.

    In this scenario we need to create an Engine
    and associate a connection with the context.

    """
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
            compare_server_default=True,
        )

        with context.begin_transaction():
            context.run_migrations()


if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()
