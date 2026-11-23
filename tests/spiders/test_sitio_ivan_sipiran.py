from conftest import fixture_response, run_parse
from scrapy.http import Response

from daii.raw.spiders.sites.ivan_sipiran import BASE, LINKS, PUBLICATIONS, RESEARCH, IvanSipiranSpider

P = "ivan-sipiran"


def test_home():
    out = run_parse(IvanSipiranSpider().parse(fixture_response("sipiran_home.html", BASE, P)))
    assert out["persona"][0]["nombre"] == "Ivan Sipiran"
    afil = {a["organizacion"]: a["rol"] for a in out["afiliacion"]}
    assert afil["Department of Computer Science at the University of Chile"] == "Assistant Professor"
    assert afil["Section of Informatics at the Pontificia Universidad Católica del Perú - PUCP"] == "researcher"
    assert afil["University of Konstanz"] == "Post-doc"
    phd, bach = out["formacion"]
    assert (phd["grado"], phd["institucion"]) == ("PhD", "Departament of Computer Science at the University of Chile")
    assert (bach["grado"], bach["anio"]) == ("Bachelor degree in Computer Science", 2005)
    assert bach["institucion"] == "Computing School at National University of Trujillo, Perú"
    assert "Graphics in Archaeology" in {a["nombre"] for a in out["area"]}
    prensa = out["actividad"]
    assert {a["tipo_actividad"] for a in prensa} == {"prensa"} and len(prensa) == 2
    assert prensa[0]["url_destino"] == "https://puntoedu.pucp.edu.pe/videos/arqueologia-en-3d/"
    # el supervisor de doctorado queda como link (Formacion no tiene campo para él)
    assert any(link["texto"] == "Dr. Benjamin Bustos" for link in out["link"])


def test_research():
    out = run_parse(IvanSipiranSpider().parse_research(fixture_response("sipiran_research.html", RESEARCH, P)))
    p = next(x for x in out["proyecto"] if x["codigo"] == "280-PNICP-BRI-2015")
    assert (p["titulo"], p["fuente"]) == (
        "Analysis of Symmetries in 3D objects and its Application to Archaeology",
        "INNOVATE- Peru",
    )
    assert len(out["proyecto"]) == 4
    sw = out["producto"][0]
    assert (sw["tipo_producto"], sw["nombre"], sw["url_destino"]) == (
        "software",
        "Harris 3D: interest point detection on meshes",
        BASE + "harris3D.html",
    )


def test_publications():
    pubs = run_parse(
        IvanSipiranSpider().parse_publications(fixture_response("sipiran_publications.html", PUBLICATIONS, P))
    )["publicacion"]
    assert len(pubs) >= 60
    assert pubs[0]["tipo_publicacion"] == "preprint" and pubs[0]["ids"] == {"arxiv": "2503.02660"}
    p = next(x for x in pubs if x["titulo"] == "Symmetria: A Synthetic Dataset for Learning in Point Clouds")
    assert (p["anio"], p["venue"], p["autores"][0]) == (2026, "IJCV", "Sipiran, I.")
    h = next(x for x in pubs if x["titulo"].startswith("Harris 3D: A robust extension"))
    assert h["autores"] == ["Ivan Sipiran", "Benjamin Bustos"] and h["anio"] == 2011


def test_links_no_son_productos():
    out = run_parse(IvanSipiranSpider().parse_links(fixture_response("sipiran_links.html", LINKS, P)))
    assert set(out) == {"link"} and any(link["texto"] == "MeshLab" for link in out["link"])


def test_cv():
    out = run_parse(
        IvanSipiranSpider().parse_cv(fixture_response("sipiran_cv.pdf", BASE + "fullcv.pdf", P, cls=Response))
    )
    konstanz = next(a for a in out["afiliacion"] if "Konstanz" in a["organizacion"])
    assert (konstanz["rol"], konstanz["desde"], konstanz["hasta"]) == (
        "Post-doctoral researcher",
        "Dic. 2013",
        "Jun. 2015",
    )
    assert ("Ph.D.", 2014) in {(f["grado"], f["anio"]) for f in out["formacion"]}
    p = next(x for x in out["proyecto"] if x["codigo"] == "1110111")
    assert (p["titulo"], p["fuente"], p["rol"]) == (
        "Interest Points Detection Algorithms for 3D Shape Matching",
        "Fondecyt (Chile)",
        "Adjunct researcher",
    )
    assert next(x for x in out["proyecto"] if x["codigo"] == "234-2018-FONDECYT")["monto"] == "US. 9,109.70 dollars"
    assert {"nombre": "Best Paper Award", "otorgante": "Big Data Visual Analytics", "anio": 2015}.items() <= next(
        d for d in out["distincion"] if d["anio"] == 2015
    ).items()
    cursos = out["dictacion"]
    assert len(cursos) >= 35
    assert {
        "nombre_curso": "Multimedia Databases",
        "semestre": "Spring",
        "anio": 2020,
        "institucion": "DCC, UChile",
    }.items() <= cursos[0].items()
    t = next(x for x in out["tesis"] if x["estudiante"] == "Renato Hermoza")
    assert (t["nivel"], t["anio"]) == ("Master", 2018)
    assert sum(a["tipo_actividad"] == "comite_programa" for a in out["actividad"]) == 7
    assert "Beauchef" not in str(out)  # sección "Personal" no se lee
