"""config/catalogos.yaml: todo código que produce el pipeline tiene nombre (si no, la interfaz muestra el código)."""

from typing import get_args

import pytest

from daii.bronze.items import TipoActividad
from daii.config import academicos, catalogos
from daii.flows.pipeline import all_spiders
from daii.gold.load import catalogo
from daii.silver.transform import INSTRUMENTO, NIVEL_FORMACION, ROL_TESIS, TIPO_PUB


@pytest.mark.parametrize(
    ("campo", "codigos"),
    [
        ("publicacion.tipo", {k for k, _ in TIPO_PUB} | {"otro"}),
        ("proyecto.instrumento", {k for k, _ in INSTRUMENTO} | {"otro"}),
        ("formacion.nivel", {k for k, _ in NIVEL_FORMACION} | {"otro"}),
        ("direcciontesis.rol", {k for k, _ in ROL_TESIS} | {"otro"}),
        ("actividad.tipo", set(get_args(TipoActividad))),
        ("academico.unidad", {a["unidad"] for a in academicos() if a.get("unidad")}),
    ],
)
def test_vocabularios_cerrados_tienen_nombre(campo, codigos):
    assert codigos - set(catalogos()[campo]) == set()


def test_todo_spider_tiene_nombre():
    nombrados = {r["codigo"] for r in catalogo() if r["campo"] == "itembronze.spider"}
    assert set(all_spiders()) - nombrados == set()
    assert next(r["nombre"] for r in catalogo() if r["codigo"] == "sitio_felipe_bravo") == (
        "Sitio personal de Felipe Bravo-Marquez"
    )
