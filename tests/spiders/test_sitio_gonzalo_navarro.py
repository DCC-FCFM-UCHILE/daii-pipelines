from conftest import fixture_response, run_parse
from scrapy.http import Response

from daii.raw.spiders.sites.gonzalo_navarro import CV, EN_CURSO, HOME, REALIZADAS, SOFTWARE, GonzaloNavarroSpider

P = "gonzalo-navarro"


def test_home():
    out = run_parse(GonzaloNavarroSpider().parse(fixture_response("navarro_sindex.html", HOME, P)))
    p = out["persona"][0]
    assert (p["nombre"], p["cargo"], p["email"]) == ("Gonzalo Navarro", "Profesor Titular", "gnavarro@dcc.uchile.cl")
    assert out["afiliacion"][0]["organizacion"].startswith("Departamento de Ciencias de Computación (DCC)")
    assert {"rol": "Coordinador del Programa de Doctorado (DCC)", "organizacion": "DCC"}.items() <= out["afiliacion"][
        1
    ].items()
    assert "Estructuras de datos comprimidas" in {a["nombre"] for a in out["area"]} and len(out["area"]) == 5
    assert {p["plataforma"] for p in out["perfil"]} == {"scholar", "dblp"}
    assert [b["titulo"] for b in out["publicacion"]] == [
        "Compact Data Structures",
        "Flexible Pattern Matching in Strings",
    ]
    assert out["publicacion"][0]["tipo_publicacion"] == "libro"
    assert out["producto"][0]["url_destino"] == "http://pizzachili.dcc.uchile.cl"

    acts = out["actividad"]
    charla = next(a for a in acts if a["titulo"] == "ACDA 2025")
    assert charla["tipo_actividad"] == "charla_invitada" and charla["fecha"] == "2025"
    assert charla["descripcion"] == "Montreal, Canadá, 30 de Julio al 1 de Agosto"
    assert sum(a["tipo_actividad"] == "charla_invitada" for a in acts) == 9
    assert next(a for a in acts if a["tipo_actividad"] == "editorial")["titulo"] == "ACM Transactions on Algorithms"
    dag = next(a for a in acts if a["titulo"] == "Dagstuhl Seminar 24472, 2024")
    assert dag["tipo_actividad"] == "organizacion_evento" and dag["rol"] == "coorganizador"
    assert {"titulo": "PODS 2027", "rol": "PC Member"}.items() <= next(a for a in acts if "PODS" in a["titulo"]).items()
    assert {d["codigo_curso"]: d["nombre_curso"] for d in out["dictacion"]}[
        "CC4102"
    ] == "Diseño y Análisis de Algoritmos"


def test_tesis():
    sp = GonzaloNavarroSpider()
    hechas = run_parse(sp.parse_tesis(fixture_response("navarro_realizadas.html", REALIZADAS, P)))["tesis"]
    assert len(hechas) >= 65
    t = hechas[0]
    assert (t["titulo"], t["estudiante"], t["anio"], t["nivel"], t["rol"], t["estado"]) == (
        "A Study of Repetitiveness Measures for Strings",
        "Cristian Urbina",
        2025,
        "Doctorado",
        "guía",
        "terminada",
    )
    assert next(x for x in hechas if x["estudiante"] == "Diego Díaz")["rol"] == "Co-guía"
    assert {x["nivel"] for x in hechas} == {"Doctorado", "Magíster", "Memorias de Ingeniería y Tesis de Licenciatura"}

    curso = run_parse(sp.parse_tesis(fixture_response("navarro_encurso.html", EN_CURSO, P)))["tesis"]
    assert len(curso) == 10  # "Futuras Tesis" no cuentan
    d = next(x for x in curso if x["estudiante"] == "Dustin Cobas")
    assert (d["nivel"], d["anio"], d["estado"]) == ("Tesis de Doctorado", 2018, "en curso")


def test_software():
    out = run_parse(GonzaloNavarroSpider().parse_software(fixture_response("navarro_software.html", SOFTWARE, P)))
    nombres = [x["nombre"] for x in out["producto"]]
    assert len(nombres) == 7 and "NR-grep: Búsqueda en Texto Flexible y Eficiente (2000)" in nombres


def test_cv():
    out = run_parse(GonzaloNavarroSpider().parse_cv(fixture_response("navarro_curric.pdf", CV, P, cls=Response)))
    phd = out["formacion"][0]
    assert phd == phd | {
        "grado": "Doctorado en Ciencias, Mención Computación",
        "institucion": "Facultad de Ciencias Físicas y Matemáticas, Universidad de Chile",
        "anio": 1998,
        "titulo_tesis": "Búsqueda Aproximada en Texto",
    }
    assert len(out["formacion"]) == 4

    proys = out["proyecto"]
    assert len(proys) >= 30
    f = next(x for x in proys if x["codigo"] == "1-260080")
    assert f == f | {
        "titulo": "Space/Time Efficient Solutions to Extend Graph Databases",
        "fuente": "Fondecyt",
        "rol": "Investigador principal",
        "anio_inicio": 2026,
        "anio_fin": 2029,
    }
    co = next(x for x in proys if x["codigo"] == "1-990627")
    assert co["rol"] == "Coinvestigador" and co["investigador_responsable"] == "Ricardo Baeza-Yates"
    assert next(x for x in proys if x["codigo"] == "VII.19")["fuente"] == "CYTED"

    dist = out["distincion"]
    assert len(dist) >= 25
    acm = next(d for d in dist if d["nombre"] == "ACM Fellow")
    assert acm["anio"] == 2022 and acm["otorgante"] == "Association for Computing Machinery"

    acts = out["actividad"]
    k = next(a for a in acts if a["titulo"] == "Adaptive Dynamic Bitvectors")
    assert k["tipo_actividad"] == "keynote" and k["fecha"] == "2025"
    assert k["evento"].startswith("SIAM Conference on Applied and Computational Discrete Algorithms (ACDA)")
    jea = next(a for a in acts if a["rol"] == "Editor en Jefe")
    assert jea["tipo_actividad"] == "editorial" and jea["fecha"] == "2016-2023"
    assert not any(a["titulo"].startswith("Participación") for a in acts)
    assert len(acts) >= 70
