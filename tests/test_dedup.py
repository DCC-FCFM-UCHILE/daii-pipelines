"""silver/dedup.py: casos reales (gold del 2026-11-24), cada regla con un caso que fusiona y uno que no."""
# ruff: noqa: E501  (los casos son registros reales completos: partirlos los vuelve ilegibles)

import polars as pl

from daii.silver import dedup
from daii.silver.transform import publicaciones

PUB = {"url": "u", "run_id": "r", "scraped_at": "s", "tipo": "publicacion", "tipo_publicacion": None, "venue": None}
PUB |= {"autores": [], "url_destino": None, "estado": None, "citas": None, "ids": "{}"}


def _pubs(*rows: dict) -> pl.DataFrame:
    return publicaciones(
        pl.DataFrame([PUB | {"item_id": f"x#{i}"} | r for i, r in enumerate(rows)], infer_schema_length=None)
    )


def _aplicar(tipo: str, *filas: dict) -> pl.DataFrame:
    rows = [
        {"persona": "p", "spider": "s", "item_id": f"s/r#{i}", "item_ids": [f"s/r#{i}"]} | f
        for i, f in enumerate(filas)
    ]
    return dedup.aplicar(tipo, pl.DataFrame(rows, infer_schema_length=None))


def _reglas(df: pl.DataFrame) -> set[str]:
    return set(df["fusiones"].explode().drop_nulls().struct.field("regla"))


def test_similar_exige_mismos_numeros_y_palabras_parecidas():
    assert dedup.similar(
        "A Particle Filter Framework for Failure Prognosis", "A Particle Filtering Framework for Failure Prognosis"
    )
    assert dedup.similar("Gradual Probabilistic Lambda Calculus", "A Gradual Probabilistic Lambda Calculus")
    assert not dedup.similar("Transient Discovery Report for 2018-02-14", "Transient Discovery Report for 2018-04-21")
    assert not dedup.similar(
        "WWW2011 Tutorial on Scalable Integration of Linked Data",
        "ISWC2011 Tutorial on Scalable Integration of Linked Data",
    )
    assert not dedup.similar(
        "Simple Low-Overhead Communication-Efficient String Reconciliation",
        "Improved Low-Overhead Communication-Efficient String Reconciliation",
    )
    assert not dedup.similar("Preface", "Prefaces")  # títulos cortos: solo igualdad


# fmt: skip


def test_doi_escrito_distinto_es_la_misma_obra():
    out = _pubs(
        {"persona": "a", "spider": "x", "titulo": "A Zipf-Like Distant Supervision Approach", "anio": 2012, "doi": "10.1007/978-3-642-34109-0_15"},
        {"persona": "a", "spider": "y", "titulo": "A zipf-like distant supervision approach", "anio": 2012, "doi": "https://doi.org/10.1007/978-3-642-34109-0-15/pdf"},
    )  # fmt: skip
    assert out.height == 1 and out["pub_key"][0] == "10.1007/978-3-642-34109-0_15"
    assert _reglas(out) == {"doi_canonico"}


def test_arxiv_se_fusiona_con_la_version_publicada():
    out = _pubs(
        {"persona": "a", "spider": "dblp", "titulo": "Emotion Intensities in Tweets", "anio": 2017, "doi": "10.48550/arXiv.1708.03696", "tipo_publicacion": "informal"},
        {"persona": "a", "spider": "openalex", "titulo": "Emotion Intensities in Tweets", "anio": 2017, "doi": "10.18653/v1/s17-1007", "tipo_publicacion": "proceedings-article"},
        {"persona": "b", "spider": "orcid", "titulo": "Emotion intensities in tweets.", "anio": 2017, "doi": None},
    )  # fmt: skip
    assert out["pub_key"].unique().to_list() == ["10.18653/v1/s17-1007"]
    assert out.filter(pl.col("persona") == "a")["tipo_publicacion"][0] == "conferencia"  # no "preprint"
    assert out["doi"].unique().to_list() == ["10.18653/v1/s17-1007"]
    assert _reglas(out) == {"arxiv_titulo", "titulo_sin_doi"}


def test_dos_dois_reales_nunca_se_fusionan():
    out = _pubs(
        {"persona": "a", "spider": "x", "titulo": "Determining Word-Emotion Associations from Tweets by Multi-label Classification", "anio": 2016, "doi": "10.1109/wi.2016.0091"},
        {"persona": "a", "spider": "y", "titulo": "Determining Word--Emotion Associations from Tweets by Multi-Label Classification", "anio": 2016, "doi": "10.1109/wi.2016.90"},
        {"persona": "a", "spider": "z", "titulo": "Determining word emotion associations from tweets by multi-label classification", "anio": 2016, "doi": None},
    )  # fmt: skip
    # el título sin DOI es ambiguo (dos DOIs): no se le asigna a ninguno
    assert sorted(out["pub_key"]) == ["10.1109/wi.2016.0091", "10.1109/wi.2016.90", "t:determining word emotion associations from tweets by multi label classification"]  # fmt: skip


def test_titulo_difuso_une_y_registra_similitud():
    out = _pubs(
        {"persona": "a", "spider": "x", "titulo": "A Particle Filter Framework for Failure Prognosis", "anio": 2005, "doi": None},
        {"persona": "b", "spider": "y", "titulo": "A Particle Filtering Framework for Failure Prognosis", "anio": 2006, "doi": None},
        {"persona": "b", "spider": "y", "titulo": "A Particle Filtering Framework for Failure Prognosis", "anio": 2015, "doi": "10.1/otra"},
    )  # fmt: skip
    # año a ±1: las dos primeras; la de 2015 tiene DOI propio y su título exacto ya está tomado por la de 2006
    aristas = out["fusiones"].explode().drop_nulls().unique()
    difusas = aristas.filter(aristas.struct.field("regla") == "titulo_difuso")
    assert difusas.len() == 1 and 0.95 <= difusas.struct.field("similitud")[0] < 1


def test_formacion_mismo_nivel_anio_e_institucion():
    waikato = {"nivel": "doctorado", "anio": 2017, "institucion": "University of Waikato"}
    out = _aplicar(
        "formacion",
        waikato | {"grado": "PhD. Computer Science"},
        waikato | {"grado": "PhD"},
        waikato | {"grado": "Doctor", "institucion": None},
        {"grado": "Doctorado en Matemáticas Aplicadas", "nivel": "doctorado", "anio": 2005, "institucion": "École Polytechnique, Francia"},
        {"grado": "Doctorado en Modelado Matemático", "nivel": "doctorado", "anio": 2005, "institucion": "Universidad de Chile"},
        {"grado": "Computer Science Engineer", "nivel": "titulo_profesional", "anio": 2010, "institucion": "Universidad de Chile"},
        {"grado": "Ingeniero Civil Industrial", "nivel": "titulo_profesional", "anio": 2010, "institucion": "University of Chile"},
    )  # fmt: skip
    assert out.height == 5
    fusion = out.filter(pl.col("anio") == 2017)
    assert fusion["grado"][0] == "PhD. Computer Science" and len(fusion["item_ids"][0]) == 3
    assert fusion["origen"][0]["institucion"] == "s/r#0" and fusion["origen"][0]["grado"] == "s/r#0"
    assert out.filter(pl.col("anio") == 2005)["origen"].null_count() == 2  # sin fusión no hay origen por campo


def test_distincion_otorgante_contenido_y_anios_distintos():
    out = _aplicar(
        "distincion",
        {"nombre": "Best Poster Award", "otorgante": "16th International Semantic Web Conference in 2017", "anio": 2017},
        {"nombre": "Best Poster Award", "otorgante": "16th International Semantic Web Conference", "anio": 2017},
        *({"nombre": "Google Research Award para América Latina", "otorgante": None, "anio": a} for a in (2016, 2017, 2019)),
    )  # fmt: skip
    assert out.height == 4


def test_actividad_ignora_url_y_respeta_fecha_y_rol():
    jornada = {"tipo_actividad": "divulgacion", "titulo": "Jornadas de Mecánica Computacional", "fecha": "05/10/2023 - 06/10/2023", "rol": "Responsable Principal"}  # fmt: skip
    out = _aplicar(
        "actividad",
        *(jornada | {"url_destino": f"https://siembraabierta.uchile.cl/initiatives/{n}"} for n in (14317, 14318, 14319)),
        {"tipo_actividad": "comite_programa", "titulo": "AAAI", "fecha": "2013, 2015, 2021", "rol": "PC Memberships", "url_destino": None},
        {"tipo_actividad": "comite_programa", "titulo": "AAAI", "fecha": "2024–2026", "rol": "SPC Memberships", "url_destino": None},
    )  # fmt: skip
    assert out.height == 3 and out["url_destino"][0].endswith("14317")


def test_afiliacion_no_une_cargos_distintos():
    uch = {"organizacion": "Universidad de Chile", "hasta": None, "url_organizacion": None}
    out = _aplicar(
        "afiliacion",
        uch | {"rol": "Professor of Electrical Engineering", "desde": None},
        uch | {"rol": "Assistant Professor of Electrical Engineering", "desde": "March 1998"},
        uch | {"rol": "Professor of Electrical Engineering", "desde": "2011", "url_organizacion": "https://ror.org/x"},
    )
    assert out.height == 2


def test_una_fila_comodin_no_encadena_registros_distintos():
    # sin fechas es compatible con ambos períodos, pero 2005–2010 y 2015–2020 no son el mismo cargo
    uch = {"organizacion": "Universidad de Chile", "rol": "Profesor", "url_organizacion": None}
    out = _aplicar(
        "afiliacion",
        uch | {"desde": None, "hasta": None},
        uch | {"desde": "2005", "hasta": "2010"},
        uch | {"desde": "2015", "hasta": "2020"},
    )
    assert out.height == 2 and sorted(out["desde"].drop_nulls()) == ["2005", "2015"]


def test_dictacion_une_roles_del_mismo_curso_y_semestre():
    curso = {"curso_id": "FI2001", "nombre_curso": "Mecánica", "anio": 2026, "semestre": "Primavera"}
    out = _aplicar(
        "dictacion",
        curso | {"rol": "Profesor Coordinador · PREGRADO", "institucion": "Facultad de Ciencias Físicas y Matemáticas"},
        curso | {"rol": "Profesor de Cátedra · PREGRADO", "institucion": "Facultad de Ciencias Físicas y Matemáticas"},
        curso | {"rol": "Profesor de Cátedra · PREGRADO", "institucion": "Campus Juan Gómez Millas"},
        curso | {"curso_id": "CI41C", "nombre_curso": "Hidrología", "rol": None, "institucion": None},
        curso | {"curso_id": "CI5101", "nombre_curso": "Hidrología", "rol": None, "institucion": None},  # el código manda
    )  # fmt: skip
    assert out.height == 3
    fi = out.filter(pl.col("curso_id") == "FI2001")
    assert fi["rol"][0] == "Profesor Coordinador · PREGRADO; Profesor de Cátedra · PREGRADO"
    assert fi["institucion"][0] == "Facultad de Ciencias Físicas y Matemáticas"


def test_perfil_misma_url_con_y_sin_identificador():
    out = _aplicar(
        "perfil",
        {"plataforma": "dblp", "url_destino": "https://dblp.org/pid/04/8612.html", "identificador": None},
        {"plataforma": "dblp", "url_destino": "http://dblp.org/pid/04/8612.html/", "identificador": "04/8612"},
        {"plataforma": "dblp", "url_destino": "http://www.informatik.uni-trier.de/~ley/db/indices/a-tree/h/Hogan:Aidan.html", "identificador": None},
    )  # fmt: skip
    assert out.height == 2 and out["identificador"][0] == "04/8612"


def _proyectos(*filas: dict) -> pl.DataFrame:
    rows = [{"persona": "p", "item_id": f"s/r#{i}", "codigo": None} | f for i, f in enumerate(filas)]
    return dedup.clave_proyecto(pl.DataFrame(rows))


def test_proyecto_codigo_canonico_sufijo_y_sin_codigo():
    out = _proyectos(
        {"titulo": "DashAI: plataforma no-code de aprendizaje automático"},
        {"titulo": "DashAI: Plataforma No-code de Aprendizaje Automático", "codigo": "I D25I10330"},
        {"titulo": "DashAI: Plataforma No-code de Aprendizaje Automático", "codigo": "ID25I10330"},
        {"titulo": "Instituto Sistemas Complejos de Ingeniería", "codigo": "PIA AFB230002"},
        {"titulo": "Instituto Sistemas Complejos de Ingeniería", "codigo": "AFB230002"},
        {"titulo": "Instituto Sistemas Complejos de Ingeniería", "codigo": "P-05-004-F"},
        {"titulo": "Basal Excellence Center \"Center for Mathematical Modeling\"", "codigo": "PFB03, AFB170001"},
        {"titulo": "BASAL Excellence Center “Center for Mathematical Modeling”", "codigo": "Basal Grant FB210005"},
    )  # fmt: skip
    assert out["clave"].to_list() == ["I D25I10330"] * 3 + ["PIA AFB230002"] * 2 + ["P-05-004-F", "PFB03, AFB170001", "Basal Grant FB210005"]  # fmt: skip
    assert _reglas(out) == {"codigo_canonico", "titulo_sin_codigo", "codigo_sufijo"}


def _tesis(*filas: dict) -> pl.DataFrame:
    base = {"persona": "p", "titulo": None, "anio": None, "estudiante": None, "nivel": None}
    return dedup.clave_tesis(pl.DataFrame([base | {"item_id": f"s/r#{i}"} | f for i, f in enumerate(filas)]))


def test_tesis_titulo_anio_cercano_y_estudiante_sin_titulo():
    out = _tesis(
        {"titulo": "Gradual System F", "anio": 2023, "estudiante": "Elizabeth Labrada", "nivel": "PhD"},
        {"titulo": "Gradual system F", "anio": 2022},
        {"titulo": "A Compact and Dynamic Caching System for RDF Graph Databases", "anio": 2024, "estudiante": "Cristóbal Miranda", "nivel": "Magíster"},
        {"estudiante": "Cristóbal Miranda", "nivel": "Masters in Computer Science"},
        {"titulo": "Identificación de daño en placas tipo sándwich", "anio": 2016, "estudiante": "Seguel Plaza, Francisco Javier"},
        {"titulo": "Caracterización experimental de las vibraciones", "anio": 2014, "estudiante": "Seguel Plaza, Francisco Javier"},
        {"estudiante": "Paloma Pérez", "anio": 2011, "nivel": "B.Sc."},
        {"estudiante": "Paloma Pérez", "anio": 2018, "nivel": "B.Sc."},
        {"anio": 2020}, {"anio": 2020},  # sin título ni estudiante: nada las identifica
    )  # fmt: skip
    c = out["clave"].to_list()
    assert c[0] == c[1] and c[2] == c[3] and len(set(c[4:])) == 6
    assert _reglas(out) == {"titulo_anio_cercano", "estudiante_sin_titulo"}
