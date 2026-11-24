import json
import logging
import sqlite3
import sys

import pytest

from daii import log
from daii.log import logger


@pytest.fixture
def logs(tmp_path, monkeypatch):
    monkeypatch.setattr(log, "DATA", tmp_path)
    yield tmp_path
    logger.remove()
    logger.add(sys.stderr)
    logging.root.handlers.clear()


def test_registros_propios_e_interceptados_llegan_a_db_archivo_y_consola(logs, capsys):
    log.setup("bronze.portafolio", spider="portafolio", run_id="r1")
    spider = type("S", (), {"name": "portafolio"})()
    with log.archivo(logs / "run" / "log.jsonl"):
        logger.bind(evento="pestania_incompleta", persona="ana", pestania="docencia").error("falló {x}")
        logging.getLogger("scrapy.core.engine").warning("cerrando", extra={"spider": spider})
    logger.complete()

    with sqlite3.connect(logs / "logs.sqlite") as db:
        db.row_factory = sqlite3.Row
        own, scrapy = db.execute("SELECT * FROM log ORDER BY ts").fetchall()
    assert (own["nivel"], own["componente"], own["evento"], own["persona"]) == (
        "ERROR",
        "bronze.portafolio",
        "pestania_incompleta",
        "ana",
    )
    assert (own["spider"], own["run_id"], own["mensaje"]) == ("portafolio", "r1", "falló {x}")
    assert json.loads(own["extra"]) == {"pestania": "docencia"}
    assert (scrapy["componente"], scrapy["spider"], scrapy["evento"]) == ("scrapy.core.engine", "portafolio", "log")

    lines = [json.loads(line) for line in (logs / "run" / "log.jsonl").read_text().splitlines()]
    assert lines[0]["record"]["extra"]["evento"] == "pestania_incompleta"

    err = capsys.readouterr().err
    assert "ERROR   bronze.portafolio [ana] pestania_incompleta: falló {x}" in err
    assert "WARNING scrapy.core.engine log: cerrando" in err

    assert (
        log.consultar(nivel="error") == [line for line in log.consultar() if "pestania_incompleta" in line]
        and len(log.consultar(spider="portafolio")) == 2
    )


def test_db_inaccesible_no_tumba_el_proceso(tmp_path, monkeypatch, capsys):
    blocked = tmp_path / "archivo"
    blocked.write_text("no es un directorio")
    monkeypatch.setattr(log, "DATA", blocked)
    try:
        log.setup("cli")
        logger.info("sigue")
    finally:
        logger.remove()
        logger.add(sys.stderr)
        logging.root.handlers.clear()
    assert "logs.sqlite no disponible" in capsys.readouterr().err


def test_migraciones_de_logs_coinciden_con_la_tabla(tmp_path):
    from alembic.autogenerate import compare_metadata
    from alembic.migration import MigrationContext
    from sqlalchemy import create_engine

    log.migrate(tmp_path / "logs.sqlite")
    with create_engine(f"sqlite:///{tmp_path / 'logs.sqlite'}").connect() as connection:
        assert compare_metadata(MigrationContext.configure(connection), log.METADATA) == []
