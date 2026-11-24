"""Logs estructurados de todo daii, con loguru.

Uso: `from daii.log import logger` y `logger.bind(evento="pagina_fallida", persona=slug).error("...")`.
Solo los puntos de entrada (CLI, flow, extensión de Scrapy) llaman `setup()`; el resto del código solo emite.

Cada registro lleva los campos de `CAMPOS` (los que no aplican quedan null). Salidas:
- consola: texto legible (`TEXTO`); dentro de un run de Prefect va al logger de Prefect;
- `archivo(path)`: JSON por línea (formato `serialize` de loguru), p. ej. bronze/<spider>/<run_id>/log.jsonl;
- `data/logs.sqlite`: una fila por registro desde INFO. Solo crece; su esquema lo versiona Alembic (`-n logs`).
"""

import json
import logging
import os
import sqlite3
import sys
import traceback
from collections.abc import Generator
from contextlib import contextmanager
from datetime import UTC
from fcntl import LOCK_EX, flock
from pathlib import Path

from alembic import command
from alembic.config import Config
from loguru import logger
from sqlalchemy import Column, Index, MetaData, String, Table, Text, create_engine

from daii.config import DATA

CAMPOS = ("componente", "evento", "spider", "persona", "run_id", "build_id", "flow_run_id", "url")
CUERPO = "{extra[componente]}{extra[_persona]} {extra[evento]}: {message}"
TEXTO = "{time:HH:mm:ss} {level:<7} " + CUERPO
MIGRATIONS = Path(__file__).parent / "logs_migrations"

METADATA = MetaData()  # aparte de SQLModel.metadata: estas tablas no son de gold
LOG = Table(
    "log",
    METADATA,
    Column("ts", String, nullable=False),
    Column("nivel", String, nullable=False),
    *(Column(c, String) for c in CAMPOS),
    Column("mensaje", Text, nullable=False),
    Column("extra", Text),  # JSON con los campos enlazados que no están en CAMPOS
    Column("excepcion", Text),
    Index("ix_log_run_id", "run_id"),
    Index("ix_log_spider_ts", "spider", "ts"),
    Index("ix_log_nivel_ts", "nivel", "ts"),
)


def logs_db() -> Path:
    return DATA / "logs.sqlite"


def _persona(record) -> None:
    persona = record["extra"].get("persona")
    record["extra"]["_persona"] = f" [{persona}]" if persona else ""


def _row(record) -> tuple:
    extra = record["extra"]
    rest = {k: v for k, v in extra.items() if k not in CAMPOS and not k.startswith("_")}
    exc = record["exception"]
    return (
        record["time"].astimezone(UTC).isoformat(),  # UTC: ts se ordena y filtra como texto
        record["level"].name,
        *(None if extra.get(c) is None else str(extra[c]) for c in CAMPOS),
        record["message"],
        json.dumps(rest, default=str, ensure_ascii=False) if rest else None,
        "".join(traceback.format_exception(exc.type, exc.value, exc.traceback)) if exc and exc.type else None,
    )


class _DbSink:
    """Inserta cada registro en logs.sqlite. Un log nunca debe tumbar un scraper: los errores van a stderr."""

    COLUMNAS = ("ts", "nivel", *CAMPOS, "mensaje", "extra", "excepcion")
    SQL = f"INSERT INTO log ({', '.join(COLUMNAS)}) VALUES ({', '.join('?' * len(COLUMNAS))})"

    def __init__(self, path: Path):
        self.path, self.db = path, None

    def __call__(self, message) -> None:
        try:
            if self.db is None:  # se abre en el hilo del sink (enqueue=True)
                self.db = sqlite3.connect(self.path, timeout=30)
                self.db.execute("PRAGMA journal_mode=WAL")
            self.db.execute(self.SQL, _row(message.record))
            self.db.commit()
        except Exception as e:  # noqa: BLE001
            sys.stderr.write(f"daii.log: no se pudo guardar en {self.path}: {e}\n")


def migrate(path: Path) -> None:
    """Lleva logs.sqlite al head de sus migraciones. Con lock: varios spiders arrancan a la vez."""
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.with_suffix(".lock").open("a") as lock:
        flock(lock, LOCK_EX)
        cfg = Config()
        cfg.set_main_option("script_location", str(MIGRATIONS))
        engine = create_engine(f"sqlite:///{path}")
        with engine.begin() as connection:
            cfg.attributes["connection"] = connection
            command.upgrade(cfg, "head")
        engine.dispose()


def _en_prefect() -> bool:
    try:
        from prefect.context import get_run_context

        get_run_context()
        return True
    except Exception:  # noqa: BLE001  fuera de un flow o task
        return False


def _a_prefect(message) -> None:
    from prefect.logging import get_run_logger

    record = message.record
    get_run_logger().log(record["level"].no, message.rstrip("\n"))


def _solo_prefect(record: logging.LogRecord) -> bool:
    return record.name.startswith("prefect")


class _Intercept(logging.Handler):
    """Lleva a loguru lo que emiten Scrapy, Twisted, scrapy-playwright y cualquier librería con `logging`."""

    def emit(self, record: logging.LogRecord) -> None:
        if record.name.startswith("prefect"):  # tienen sus propios handlers; reenviarlos haría un ciclo
            return
        try:
            level: str | int = logger.level(record.levelname).name
        except ValueError:
            level = record.levelno
        fields = {"componente": record.name, "_externo": True}
        if spider := getattr(record, "spider", None):
            fields["spider"] = getattr(spider, "name", str(spider))
        logger.bind(**fields).opt(exception=record.exc_info).log(level, record.getMessage())


def setup(componente: str, *, prefect: bool = False, db: bool = True, **contexto) -> None:
    """Configura todas las salidas para este proceso. Se puede llamar de nuevo (reemplaza la configuración)."""
    defaults = dict.fromkeys(CAMPOS) | {"evento": "log", "_persona": ""}
    logger.remove()
    logger.configure(extra=defaults | {"componente": componente} | contexto, patcher=_persona)
    level = os.environ.get("LOG_LEVEL", "INFO")
    if prefect:  # dentro de un run, la consola la escribe Prefect (y queda en su UI)
        # Solo los registros propios van a Prefect: los de librerías (httpx del propio cliente de Prefect, entre
        # otros) volverían a pasar por logging y harían un ciclo.
        def to_prefect(record) -> bool:
            return not record["extra"].get("_externo") and _en_prefect()

        logger.add(sys.stderr, level=level, format=TEXTO, filter=lambda r: not to_prefect(r))
        logger.add(_a_prefect, level=level, format=CUERPO, colorize=False, filter=to_prefect)  # Prefect pone la hora
    else:
        logger.add(sys.stderr, level=level, format=TEXTO)
    if db:
        path = logs_db()
        try:
            migrate(path)
            logger.add(_DbSink(path), level="INFO", enqueue=True, catch=True)
        except Exception as e:  # noqa: BLE001
            sys.stderr.write(f"daii.log: logs.sqlite no disponible ({e}); solo consola y archivos\n")
    root = logging.getLogger()
    for handler in root.handlers:  # la consola de Prefect sigue mostrando lo de Prefect; el resto va por loguru
        if type(handler).__module__.startswith("prefect"):  # no otros, p. ej. el contador log_count/* de Scrapy
            handler.addFilter(_solo_prefect)
    root.handlers = [h for h in root.handlers if not isinstance(h, _Intercept)] + [_Intercept()]
    root.setLevel(logging.INFO)
    # httpx: una línea por request, incluido cada envío de logs a Prefect; alembic: 3 líneas por cada gold
    for noisy in ("httpx", "httpcore", "alembic"):
        logging.getLogger(noisy).setLevel(logging.WARNING)


@contextmanager
def archivo(path: Path) -> Generator[None]:
    """Copia en JSON por línea los registros mientras dura el bloque (todo desde INFO)."""
    path.parent.mkdir(parents=True, exist_ok=True)
    sink = logger.add(path, level="INFO", serialize=True, enqueue=True)
    try:
        yield
    finally:
        logger.remove(sink)


NIVELES = ("TRACE", "DEBUG", "INFO", "SUCCESS", "WARNING", "ERROR", "CRITICAL")


def consultar(
    *,
    run_id: str | None = None,
    spider: str | None = None,
    nivel: str = "INFO",
    desde: str | None = None,
    limite: int = 200,
) -> list[str]:
    """Últimos registros de logs.sqlite que cumplen los filtros, en orden cronológico y con el formato de consola."""
    if nivel.upper() not in NIVELES:
        raise ValueError(f"nivel desconocido: {nivel}")
    niveles = NIVELES[NIVELES.index(nivel.upper()) :]
    where = [f"nivel IN ({', '.join('?' * len(niveles))})"]
    params: list = list(niveles)
    for column, value, op in (("run_id", run_id, "="), ("spider", spider, "="), ("ts", desde, ">=")):
        if value:
            where.append(f"{column} {op} ?")
            params.append(value)
    sql = f"SELECT * FROM log WHERE {' AND '.join(where)} ORDER BY ts DESC LIMIT ?"
    if not logs_db().exists():
        return []
    with sqlite3.connect(f"{logs_db().resolve().as_uri()}?mode=ro", uri=True) as db:
        db.row_factory = sqlite3.Row
        rows = db.execute(sql, [*params, limite]).fetchall()
    return [
        f"{r['ts'][:19].replace('T', ' ')} {r['nivel']:<7} {r['componente']}"
        + (f" [{r['persona']}]" if r["persona"] else "")
        + f" {r['evento']}: {r['mensaje']}"
        + (f"\n{r['excepcion']}" if r["excepcion"] else "")
        for r in reversed(rows)
    ]
