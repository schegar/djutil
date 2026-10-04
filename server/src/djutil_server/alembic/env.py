"""Alembic environment: engine is passed via config.attributes."""

from alembic import context

config = context.config

target_metadata = None


def run_migrations() -> None:
    engine = config.attributes.get("engine")
    if engine is None:
        raise RuntimeError("alembic env: no engine in config.attributes")
    with engine.connect() as connection:
        context.configure(connection=connection, target_metadata=target_metadata)
        with context.begin_transaction():
            context.run_migrations()


run_migrations()
