import polars as pl
import pytest

from daii.gold import load
from daii.quality import checks
from daii.silver.transform import ROL_TESIS, classify, publicaciones

BASE = {"url": "u", "run_id": "r", "scraped_at": "s", "tipo": "publicacion", "tipo_publicacion": None, "venue": None}
BASE |= {"autores": [], "url_destino": None, "estado": None, "citas": None, "ids": "{}"}


def _pubs(*rows: dict) -> pl.DataFrame:
    return publicaciones(pl.DataFrame([BASE | r for r in rows], infer_schema_length=None))


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
    monkeypatch.setattr(load, "GOLD", gold_db.parent)
    monkeypatch.setattr(load, "GOLD_DB", gold_db)
    monkeypatch.setattr(load, "BRONZE", tmp_path / "bronze")
    tesis = {"titulo": None, "anio": None, "nivel": "PhD", "programa": None, "estado": None, "url_destino": None}
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
