import json
import sqlite3

import polars as pl
import pytest
from sqlmodel import SQLModel

from daii.bronze.items import bronze_item
from daii.config import academicos
from daii.flows.pipeline import all_spiders
from daii.gold import load  # registra los modelos gold en SQLModel.metadata
from daii.quality import checks
from daii.silver import transform
from daii.silver.transform import ROL_TESIS, classify, publicaciones

BASE = {"url": "u", "run_id": "r", "scraped_at": "s", "tipo": "publicacion", "tipo_publicacion": None, "venue": None}
BASE |= {"autores": [], "url_destino": None, "estado": None, "citas": None, "ids": "{}"}


def _pubs(*rows: dict) -> pl.DataFrame:
    return publicaciones(
        pl.DataFrame([BASE | {"item_id": f"x#{i}"} | r for i, r in enumerate(rows)], infer_schema_length=None)
    )


def test_titulos_genericos_no_se_funden_entre_obras():
    out = _pubs(
        {"persona": "a", "spider": "x", "titulo": "Preface", "anio": 2011, "doi": None},
        {"persona": "b", "spider": "x", "titulo": "Preface", "anio": 2025, "doi": None},
        {"persona": "b", "spider": "y", "titulo": "Preface", "anio": 2020, "doi": "10.1234/otra"},
    )
    assert sorted(out["pub_key"]) == ["10.1234/otra", "t:preface|2011", "t:preface|2025"]


def test_titulo_largo_hereda_doi_y_doi_se_limpia():
    out = _pubs(
        {"persona": "a", "spider": "orcid", "titulo": "Gradual Sensitivity Typing for Privacy", "anio": 2025,
         "doi": "bar050\nHTTPS://doi.org/10.1109/CSF.2025.21"},
        {"persona": "a", "spider": "sitio_x", "titulo": "Gradual sensitivity typing for privacy.", "anio": 2024,
         "doi": None},
    )  # fmt: skip
    assert out.height == 1 and out["pub_key"][0] == "10.1109/csf.2025.21"
    assert out["fuentes"][0].to_list() == ["orcid", "sitio_x"]
    assert out["anio"][0] == 2024  # el sitio personal gana a orcid


def test_prioridad_sitio_luego_portafolio_luego_resto():
    spiders = ["openalex", "cmm", "orcid", "portafolio", "sitio_x"]
    assert sorted(spiders, key=transform._prio) == ["sitio_x", "portafolio", "orcid", "openalex", "cmm"]
    # orden propio de la persona: esas fuentes primero, el resto sigue el orden global
    propia = sorted(spiders, key=lambda s: transform._prio(s, ["cmm", "sitio"]))
    assert propia == ["cmm", "sitio_x", "portafolio", "orcid", "openalex"]


def test_prioridad_por_persona_decide_el_campo(monkeypatch):
    monkeypatch.setattr(transform, "academicos", lambda: [{"slug": "a", "prioridad": ["cmm"]}])
    out = _pubs(
        {"persona": "a", "spider": "sitio_x", "titulo": "Una obra cualquiera de prueba", "anio": 2020, "doi": None},
        {"persona": "a", "spider": "cmm", "titulo": "Una obra cualquiera de prueba", "anio": 2021, "doi": None},
        {"persona": "b", "spider": "sitio_x", "titulo": "Una obra cualquiera de prueba", "anio": 2020, "doi": None},
        {"persona": "b", "spider": "cmm", "titulo": "Una obra cualquiera de prueba", "anio": 2021, "doi": None},
    )  # fmt: skip
    assert dict(zip(out["persona"], out["anio"], strict=True)) == {"a": 2021, "b": 2020}


def test_prioridad_en_config_usa_spiders_existentes():
    validos = {s for s in all_spiders() if not s.startswith("sitio_")} | {"sitio"}
    for a in academicos():
        assert set(a.get("prioridad", [])) <= validos, a["slug"]


@pytest.mark.parametrize(
    ("texto", "rol"),
    [
        ("Participación como Profesor Guía", "guia"),
        ("Co-guía", "coguia"),
        ("Co-advised with Éric Tanter", "coguia"),
        ("co-supervisor", "coguia"),
        ("As an undergraduate advisor, I worked with:", "guia"),
        ("Comisión", "comision"),
        ("", "otro"),
    ],
)
def test_rol_tesis(texto, rol):
    assert classify(texto, ROL_TESIS) == rol


def test_gold_se_construye_y_respeta_config(tmp_path, monkeypatch):
    silver, gold_db = tmp_path / "silver", tmp_path / "gold" / "daii.sqlite"
    silver.mkdir()
    monkeypatch.setattr(load, "SILVER", silver)
    monkeypatch.setattr(load, "GOLD_DB", gold_db)
    monkeypatch.setattr(load, "BRONZE", tmp_path / "bronze")
    tesis = {
        "item_id": "s/r#1",
        "item_ids": ["s/r#1"],
        "titulo": None,
        "anio": None,
        "nivel": "PhD",
        "programa": None,
        "estado": None,
        "url_destino": None,
    }
    pl.DataFrame(
        [
            {"persona": "aidan-hogan", "spider": "s", "estudiante": "Ana", "rol_norm": "guia", **tesis},
            {"persona": "aidan-hogan", "spider": "s", "estudiante": "Beto", "rol_norm": "guia", **tesis},
            {"persona": "fuera-de-config", "spider": "s", "estudiante": "Cata", "rol_norm": "guia", **tesis},
        ]
    ).write_parquet(silver / "tesis.parquet")

    titulada = tesis | {"titulo": "Gradual sensitivity types", "anio": 2021}
    pl.concat(
        [
            pl.read_parquet(silver / "tesis.parquet"),
            pl.DataFrame(
                [  # misma tesis desde dos fuentes: una trae estudiante y la otra no
                    {"persona": "matias-toro", "spider": "a", "estudiante": "Damián", "rol_norm": "guia", **titulada},
                    {"persona": "matias-toro", "spider": "b", "estudiante": None, "rol_norm": "guia", **titulada},
                ]
            ),
        ],
        how="vertical_relaxed",
    ).write_parquet(silver / "tesis.parquet")

    pl.DataFrame(schema=dict.fromkeys(transform.PROCEDENCIA, pl.String)).write_parquet(silver / "item.parquet")
    counts = load.build()
    assert gold_db.exists() and not gold_db.with_suffix(".tmp").exists()
    # sin título el estudiante distingue (Ana ≠ Beto); con título no (1 sola); fuera de config no entra
    assert counts["tesis"] == 3


def test_quality_spider_que_no_arranco(tmp_path, monkeypatch):
    monkeypatch.setattr(checks, "BRONZE", tmp_path)
    res = checks.check("orcd", tmp_path / "orcd" / "20260101T000000Z")  # el run nunca se creó
    assert res["status"] == "fail"


def test_publicacion_sin_doi_en_corrida_parcial():
    out = _pubs({"persona": "a", "spider": "sitio_x", "titulo": "Una publicación", "doi": None, "anio": None})
    assert out["doi"].to_list() == [None]
    assert out["pub_key"].to_list() == ["t:una publicacion|?"]


def test_obras_de_homonimos_de_weber_en_openalex_se_descartan():
    weber = {"persona": "richard-weber", "spider": "openalex", "doi": None}
    out = _pubs(
        weber | {"titulo": "On the Cover", "anio": 2009},
        weber | {"titulo": "Dielektrizitätskonstanten wässriger Lösungen", "anio": 1931},
        weber | {"titulo": "Data mining for credit scoring models", "anio": 2010},
        {"persona": "otra", "spider": "openalex", "titulo": "On the Cover", "doi": None, "anio": 2009},
    )
    assert sorted(zip(out["persona"], out["titulo"], strict=True)) == [
        ("otra", "On the Cover"),
        ("richard-weber", "Data mining for credit scoring models"),
    ]


META = {"scraperun", "datarelease", "catalogo"}  # metadatos y referencia (config), sin evidencia


def test_trazabilidad_de_bronze_a_gold(tmp_path):
    """Toda fila de gold tiene evidencia que lleva a una línea de items.jsonl; los campos fusionados, a su ítem."""
    base = {"persona": "aidan-hogan", "url": "https://x", "scraped_at": "s", "observacion_id": "obs1"}
    pub = {"tipo": "publicacion", "titulo": "Knowledge graphs for the semantic web", "doi": "10.1/kg", "autores": []}
    items = {
        "orcid": [
            pub | {"anio": 2021, "venue": None},  # orcid gana: año de orcid, venue (vacío aquí) de dblp
            {"tipo": "area", "nombre": "Semantic Web"},
            {"tipo": "persona", "nombre": "Aidan Hogan", "cargo": "Profesor"},
        ],
        "dblp": [
            pub | {"anio": 2020, "venue": "ESWC"},
            {"tipo": "area", "nombre": "Semantic Web"},  # idéntica a la de orcid: una fila, dos ítems
            {"tipo": "dictacion", "nombre_curso": "Bases de datos", "codigo_curso": "cc3201", "anio": 2024},
            {"tipo": "proyecto", "titulo": "Grafos", "codigo": "1221926", "rol": "IR"},
        ],
    }
    runs = []
    for spider, rows in items.items():
        run = tmp_path / "bronze" / spider / "r1"
        run.mkdir(parents=True)
        # como los escribe ValidatePipeline: el ítem validado con todos sus campos
        lines = [
            bronze_item.validate_python(base | {"spider": spider, "run_id": "r1"} | r).model_dump_json() for r in rows
        ]
        (run / "items.jsonl").write_text("\n".join(lines) + "\n")
        runs.append(run)
    silver, db = tmp_path / "silver", tmp_path / "daii.sqlite"
    transform.build(silver, runs)

    area = pl.read_parquet(silver / "area.parquet")
    assert area.height == 1 and sorted(area["item_ids"][0]) == ["dblp/r1#2", "orcid/r1#2"]
    origen = pl.read_parquet(silver / "publicacion.parquet")["origen"][0]
    assert origen["anio"] == "orcid/r1#1" and origen["venue"] == "dblp/r1#1"

    load.build(silver, db, run_rows=[])
    con = sqlite3.connect(db)
    q = lambda sql: con.execute(sql).fetchall()  # noqa: E731
    # cada fila de cada tabla de datos (también las que se agreguen) está respaldada, y cada ítem citado existe
    datos = [t for t in SQLModel.metadata.sorted_tables if t.name not in {"evidencia", "itembronze"} | META]
    con_filas = {"academico", "area", "publicacion", "publicacionacademico", "curso", "dictacion", "proyecto"}
    for t in datos:
        fila = ", ".join(f"t.{c.name}" for c in t.primary_key.columns)
        huerfanas = f"SELECT COUNT(*) FROM {t.name} t WHERE NOT EXISTS (SELECT 1 FROM evidencia e"
        huerfanas += f" WHERE e.tabla = '{t.name}' AND e.campo = '' AND e.fila_id = json_array({fila}))"
        assert q(huerfanas) == [(0,)], t.name
    assert all(q(f"SELECT COUNT(*) FROM {t}")[0][0] > 0 for t in con_filas)
    # el explorador arma `fuentes` desde la evidencia: un PK mal escrito en su SQL dejaría la lista vacía
    from daii.explorar import datos as explorador

    for tipo, (_, sql, _) in explorador.TIPOS.items():
        assert "[]" not in {r[-1] for r in q(sql)}, tipo
    # y muestra el nombre del catálogo, no el código (publicación sin tipo de la fuente → "otro")
    assert {r[3] for r in q(explorador.TIPOS["publicacion"][1])} == {"Otro"}
    assert q("SELECT COUNT(*) FROM evidencia WHERE item_id NOT IN (SELECT id FROM itembronze)") == [(0,)]
    # campo a campo: año de orcid, venue de dblp; nombre del académico de config
    assert q("SELECT campo, item_id FROM evidencia WHERE tabla = 'publicacion' AND campo IN ('anio', 'venue')"
             " ORDER BY campo") == [("anio", "orcid/r1#1"), ("venue", "dblp/r1#1")]  # fmt: skip
    assert q("SELECT item_id FROM evidencia WHERE tabla = 'academico' AND fila_id = '[\"aidan-hogan\"]'"
             " AND campo = 'nombre'") == [("config:academicos.yaml",)]  # fmt: skip
    assert q("SELECT item_id FROM evidencia WHERE tabla = 'academico' AND campo = 'cargo'") == [("orcid/r1#3",)]
    # item_id → línea exacta de bronze, con su página archivada
    spider, run_id, url, obs = q("SELECT spider, run_id, url, observacion_id FROM itembronze WHERE id = 'dblp/r1#3'")[0]
    linea = (tmp_path / "bronze" / spider / run_id / "items.jsonl").read_text().splitlines()[3 - 1]
    assert json.loads(linea)["nombre_curso"] == "Bases de datos" and (url, obs) == ("https://x", "obs1")
