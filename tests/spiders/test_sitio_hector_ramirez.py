from conftest import fixture_response, run_parse

from daii.raw.spiders.sites.hector_ramirez import (
    HOME,
    PROJECTS,
    PUBLICATIONS,
    SERVICE,
    STUDENTS,
    HectorRamirezSpider,
)

P = "hector-ramirez"


def test_home():
    out = run_parse(HectorRamirezSpider().parse(fixture_response("ramirez_home.html", HOME, P)))
    p = out["persona"][0]
    assert (p["nombre"], p["cargo"], p["email"]) == ("Héctor Ramírez", "Full Professor", "hramirez@dim.uchile.cl")
    assert [(a["rol"], a["organizacion"]) for a in out["afiliacion"]] == [
        ("Full Professor", "Mathematical Engineering Department, Universidad de Chile"),
        ("Director", "Center for Mathematical Modeling (CMM), Universidad de Chile - CNRS"),
    ]
    assert "Conic programming (SDP, SOCP)" in {a["nombre"] for a in out["area"]} and len(out["area"]) == 6
    cursos = {d["nombre_curso"]: d for d in out["dictacion"]}
    assert (cursos["Optimal Control"]["codigo_curso"], cursos["Optimal Control"]["anio"]) == ("MA4703", 2026)
    assert "Optimal Control (Theory & Lab)" in cursos and len(cursos) == 10


def test_service():
    out = run_parse(HectorRamirezSpider().parse_service(fixture_response("ramirez_academic-service.html", SERVICE, P)))
    acts = out["actividad"]
    assert {"tipo_actividad": "editorial", "titulo": "Operation Research Letters", "fecha": "2017-now"}.items() <= acts[
        0
    ].items()
    assert acts[0]["rol"] == "Chief Editor of Continuous Optimization Area"
    assert sum(a["rol"] == "Associate Editor" for a in acts) == 3
    assert any(a["tipo_actividad"] == "revisor" and "FONDECYT" in a["titulo"] for a in acts)
    ev = next(a for a in acts if a["titulo"] == "10th French-Chilean Journeys on Optimization")
    assert (ev["tipo_actividad"], ev["fecha"], ev["descripcion"]) == (
        "organizacion_evento",
        "July 8-11, 2025",
        "Rouen, France",
    )
    assert sum(a["tipo_actividad"] == "organizacion_evento" for a in acts) >= 25


def test_projects():
    ps = run_parse(HectorRamirezSpider().parse_projects(fixture_response("ramirez_projects.html", PROJECTS, P)))[
        "proyecto"
    ]
    assert len(ps) >= 40
    f = next(p for p in ps if p["codigo"] == "1262466")
    assert (f["fuente"], f["titulo"], f["rol"], f["anio_inicio"], f["anio_fin"]) == (
        "FONDECYT",
        "Second order and stability analysis in nonlinear conic optimization",
        "responsible",
        2026,
        2030,
    )
    g = next(p for p in ps if p["codigo"] == "1200355")
    assert (g["rol"], g["investigador_responsable"]) == ("associate researcher", "Pedro Gajardo")
    assert any(p["titulo"] == "DYnamical Microbial and Environmental eCOSystems" for p in ps)


def test_publications():
    pubs = run_parse(
        HectorRamirezSpider().parse_publications(fixture_response("ramirez_publications.html", PUBLICATIONS, P))
    )["publicacion"]
    assert len(pubs) >= 65
    p = next(x for x in pubs if x["doi"] == "10.1007/s10957-024-02562-8")
    assert p["titulo"].startswith("Facial approach for constructing stationary points")
    assert (p["venue"], p["anio"], p["autores"], p["tipo_publicacion"]) == (
        "JOTA",
        2025,
        ["J. Madariaga", "H. Ramírez"],
        "Journal articles",
    )
    assert pubs[0]["estado"] == "Submitted"
    assert {x["tipo_publicacion"] for x in pubs} == {
        "Journal articles",
        "Conference proceedings (peer reviewed)",
        "Nonpublished technical reports",
        "Books",
    }
    assert any(x["titulo"] == "Grafos: Fundamentos and Algoritmos" and x["anio"] == 2011 for x in pubs)


def test_students():
    ts = run_parse(
        HectorRamirezSpider().parse_students(fixture_response("ramirez_student-s-formation.html", STUDENTS, P))
    )["tesis"]
    assert len(ts) == 23  # las estadías ("Internship") no son tesis
    t = next(x for x in ts if x["estudiante"] == "Alejandro Rojas")
    assert (t["titulo"], t["anio"], t["nivel"], t["rol"]) == (
        "Algunos problemas de modelamiento en bioprocesos",
        2016,
        "PhD Thesis",
        "guía",
    )
    assert next(x for x in ts if x["estudiante"] == "Lucas Motta")["estado"] == "en curso"
    assert next(x for x in ts if x["estudiante"] == "David Sossa")["rol"] == "co-guía"
