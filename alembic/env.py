from logging.config import fileConfig

from sqlalchemy import engine_from_config
from sqlalchemy import pool

from alembic import context

# Import your models and settings
# Import Base directly from schema to avoid circular imports with database.py
import sys
import importlib.util
from pathlib import Path
from dotenv import load_dotenv

# Add parent directory to path so we can import our modules
project_root = Path(__file__).parent.parent
sys.path.insert(0, str(project_root))

# Load .env file explicitly (Pydantic might not find it when run from alembic)
env_path = project_root / ".env"
load_dotenv(env_path)

# Import Base directly from schema.py file to avoid loading db/__init__.py
# which would trigger database.py and create an engine
schema_path = project_root / "db" / "schema.py"
spec = importlib.util.spec_from_file_location("db.schema", schema_path)
schema_module = importlib.util.module_from_spec(spec)
spec.loader.exec_module(schema_module)
Base = schema_module.Base

from config.settings import get_settings  # noqa: E402

# this is the Alembic Config object, which provides
# access to the values within the .ini file in use.
config = context.config

# Get database URL from Pydantic settings instead of alembic.ini
# This ensures we use the same configuration as the rest of the app
# Note: We don't set it in config because ConfigParser doesn't like % in URLs
settings = get_settings()
database_url = settings.database.url

# Interpret the config file for Python logging.
# This line sets up loggers basically.
if config.config_file_name is not None:
    fileConfig(config.config_file_name)

# Set target_metadata to your models' metadata
# This is what Alembic uses to detect schema changes
target_metadata = Base.metadata

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
    # Use our database_url variable instead of reading from config
    context.configure(
        url=database_url,
        target_metadata=target_metadata,
        literal_binds=True,
        dialect_opts={"paramstyle": "named"},
        compare_type=True,  # Detect column type changes
        compare_server_default=True,  # Detect default value changes
    )

    with context.begin_transaction():
        context.run_migrations()


def run_migrations_online() -> None:
    """Run migrations in 'online' mode.

    In this scenario we need to create an Engine
    and associate a connection with the context.

    """
    # Create engine directly from our database_url instead of using config
    from sqlalchemy import create_engine
    connectable = create_engine(database_url, poolclass=pool.NullPool)

    with connectable.connect() as connection:
        context.configure(
            connection=connection,
            target_metadata=target_metadata,
            compare_type=True,  # Detect column type changes
            compare_server_default=True,  # Detect default value changes
        )

        with context.begin_transaction():
            context.run_migrations()


if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()
