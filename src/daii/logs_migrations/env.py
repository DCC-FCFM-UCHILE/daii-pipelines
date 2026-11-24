"""Alembic para data/logs.sqlite. A diferencia de gold, esta base es persistente: las migraciones sí la
modifican en sitio. Uso desde la CLI: `alembic -n logs -x db=<ruta.sqlite> ...`."""

from alembic import context
from sqlalchemy import create_engine

from daii.log import METADATA


def run() -> None:
    connection = context.config.attributes.get('connection')
    if connection is None:
        db = context.get_x_argument(as_dictionary=True).get('db')
        if not db:
            raise SystemExit('Indique la base: alembic -n logs -x db=<ruta.sqlite> ...')
        with create_engine(f'sqlite:///{db}').begin() as connection:
            _configure(connection)
    else:
        _configure(connection)


def _configure(connection) -> None:
    context.configure(connection=connection, target_metadata=METADATA, render_as_batch=True)
    with context.begin_transaction():
        context.run_migrations()


run()
