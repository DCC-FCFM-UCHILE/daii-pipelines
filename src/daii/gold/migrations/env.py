"""Alembic para gold. Gold se reconstruye desde cero en cada publicación: las migraciones definen y versionan el
esquema (tabla `alembic_version` en cada SQLite), no migran datos en sitio."""

from alembic import context
from sqlmodel import SQLModel, create_engine

from daii.config import GOLD_DB
from daii.gold import models  # noqa: F401  registra las tablas en SQLModel.metadata


def run() -> None:
    connection = context.config.attributes.get("connection")
    if connection is None:  # CLI: `alembic -x db=<ruta> ...`; por defecto, la gold vigente
        db = context.get_x_argument(as_dictionary=True).get("db", str(GOLD_DB))
        with create_engine(f"sqlite:///{db}").begin() as connection:
            _configure(connection)
    else:
        _configure(connection)


def _configure(connection) -> None:
    # render_as_batch: SQLite no soporta ALTER COLUMN; Alembic recrea la tabla.
    context.configure(connection=connection, target_metadata=SQLModel.metadata, render_as_batch=True)
    with context.begin_transaction():
        context.run_migrations()


run()
