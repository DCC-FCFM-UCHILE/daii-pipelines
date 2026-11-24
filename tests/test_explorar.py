import json

import pytest
import streamlit as st
from streamlit.testing.v1 import AppTest

from daii import log, versions
from daii.explorar import datos
from daii.gold import load
from daii.quality import checks


@pytest.fixture
def data(tmp_path, monkeypatch):
    """data/ temporal con dos versiones publicadas desde runs bronze reales (formato de items.jsonl)."""
    bronze, gold = tmp_path / "bronze", tmp_path / "gold" / "daii.sqlite"
    for module, field, value in (
        (versions, "DATA", tmp_path),
        (versions, "VERSIONS", tmp_path / "versions"),
        (versions, "BRONZE", bronze),
        (versions, "GOLD_DB", gold),
        (load, "BRONZE", bronze),
        (checks, "BRONZE", bronze),
        (log, "DATA", tmp_path),
        (datos, "BRONZE", bronze),
        (datos, "GOLD_DB", gold),
        (datos, "SILVER", tmp_path / "silver"),
        (datos, "VERSIONS", tmp_path / "versions"),
    ):
        monkeypatch.setattr(module, field, value)
    st.cache_data.clear()

    def run(name: str, areas: list[str]) -> None:
        directory = bronze / "orcid" / name
        directory.mkdir(parents=True)
        (directory / "quality.json").write_text(json.dumps({"status": "ok", "problems": [], "counts": {"area": 1}}))
        base = {"tipo": "area", "persona": "aidan-hogan", "spider": "orcid", "url": "https://orcid.org/x"}
        (directory / "items.jsonl").write_text("".join(json.dumps(base | {"nombre": a}) + "\n" for a in areas))

    run("20261123T175501Z", ["Semantic Web"])
    versions.publish(versions.prepare())
    run("20261123T185212Z", ["Semantic Web", "Knowledge Graphs"])
    publicada = versions.prepare()
    versions.publish(publicada)
    st.cache_data.clear()
    return publicada


def test_loaders_leen_la_version_publicada(data):
    assert datos.release()["build_id"] == data
    assert datos.silver_dir() == versions.VERSIONS / data / "silver"
    gold = datos.capa("gold", "area")
    assert sorted(gold["nombre"].to_list()) == ["Knowledge Graphs", "Semantic Web"]
    assert datos.con_fuente(gold)["fuente"].unique().to_list() == ["orcid"]
    assert datos.bronze("area").height == 2  # solo el run en uso, no el anterior
    embudo = {r["capa"]: r["filas"] for r in datos.embudo().rows(named=True) if r["tipo"] == "Áreas"}
    assert embudo == {"bronze": 2, "silver": 2, "gold": 2}
    fila = datos.silver("area").filter(datos.pl.col("nombre") == "Knowledge Graphs").row(0, named=True)
    assert datos.origen(fila, "area")["nombre"].to_list() == ["Knowledge Graphs"]
    # silver normalizó el texto: el rastro cae al título normalizado
    assert datos.origen(fila | {"nombre": "knowledge  graphs"}, "area")["nombre"].to_list() == ["Knowledge Graphs"]
    # las capas no se multiplican por fuente (silver y gold traen una fila por dato y persona)
    assert datos.capa("gold", "area").height == datos.gold("area").height
    nulos = datos.nulos(datos.con_fuente(datos.capa("bronze", "area")))
    assert nulos.filter(datos.pl.col("campo") == "nombre")["pct_nulos"].to_list() == [0.0]
    assert datos.nulos(datos.con_fuente(datos.capa("gold", "publicacion"))).is_empty()  # tipo sin filas


def _pagina(nombre: str, modo: str, persona: str | None = None) -> None:
    import importlib

    import streamlit as st

    st.session_state["modo"] = modo
    if persona:
        st.query_params["persona"] = persona
    importlib.import_module(f"daii.explorar.{nombre}").pagina()


@pytest.mark.parametrize("modo", ["DAII", "Pipeline"])
@pytest.mark.parametrize("nombre", ["academicos", "agregados", "modelo", "conciliacion", "runs", "versiones", "logs"])
def test_paginas_sin_errores(data, nombre, modo):
    at = AppTest.from_function(_pagina, args=(nombre, modo), default_timeout=30).run()
    assert not at.exception


def test_ficha_y_rastro_por_capas(data):
    at = AppTest.from_function(_pagina, args=("academicos", "Pipeline", "aidan-hogan"), default_timeout=30).run()
    assert not at.exception
    assert at.title[0].value == "Aidan Hogan"
    assert any(t.label.startswith("Áreas") for t in at.tabs)


def test_diff_entre_versiones(data):
    at = AppTest.from_function(_pagina, args=("versiones", "Pipeline"), default_timeout=30).run()
    assert not at.exception
    assert any(e.label.startswith("area:") for e in at.expander)


def test_estados_vacios(tmp_path, monkeypatch):
    monkeypatch.setattr(datos, "GOLD_DB", tmp_path / "no.sqlite")
    monkeypatch.setattr(datos, "BRONZE", tmp_path / "bronze")
    monkeypatch.setattr(versions, "VERSIONS", tmp_path / "versions")
    monkeypatch.setattr(datos, "VERSIONS", tmp_path / "versions")
    monkeypatch.setattr(datos, "SILVER", tmp_path / "silver")
    monkeypatch.setattr(log, "DATA", tmp_path)
    st.cache_data.clear()
    for nombre in ("academicos", "agregados", "modelo", "conciliacion", "runs", "versiones", "logs"):
        at = AppTest.from_function(_pagina, args=(nombre, "Pipeline"), default_timeout=30).run()
        assert not at.exception, nombre
        assert at.info, f"{nombre} debe explicar qué falta"


def test_modelo_desde_el_codigo():
    from daii.bronze.items import Publicacion
    from daii.explorar import modelo

    assert modelo.comentarios(modelo.models.Publicacion)["id"] == 'DOI o "t:<título normalizado>"'
    assert modelo.comentarios(Publicacion)["persona"] == "slug de config/academicos.yaml"  # heredado de _Base
    cols = modelo._columnas_gold("publicacionacademico", modelo.models.PublicacionAcademico)
    assert cols.filter(modelo.pl.col("campo") == "academico_id")["clave"].to_list() == ["PK · → academico"]
    dot = modelo._diagrama()
    assert "publicacionacademico -> academico;" in dot and "scraperun" not in dot


def test_modelo_con_gold_mas_viejo_que_el_codigo(data):
    import sqlite3

    with sqlite3.connect(datos.GOLD_DB) as db:  # p. ej. un modelo nuevo antes de `make gold`
        db.execute("DROP TABLE metrica")
    st.cache_data.clear()
    for modo in ("DAII", "Pipeline"):
        at = AppTest.from_function(_pagina, args=("modelo", modo), default_timeout=30).run()
        assert not at.exception, modo
