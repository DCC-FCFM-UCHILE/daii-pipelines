from conftest import fixture_response, run_parse
from scrapy.http import Response

from daii.raw.spiders.sites.jorge_silva import CV, HOME, PUBLICACIONES, JorgeSilvaSpider

P = "jorge-silva"


def test_home():
    out = run_parse(JorgeSilvaSpider().parse(fixture_response("silva_home.html", HOME, P)))
    assert out["persona"][0]["nombre"] == "Jorge F. Silva"
    assert out["persona"][0]["cargo"] == "Professor of Electrical Engineering"
    assert {p["plataforma"] for p in out["perfil"]} >= {"scholar", "linkedin", "github"}
    assert "Information Theory" in {a["nombre"] for a in out["area"]}
    phd = out["formacion"][0]
    assert phd["grado"] == "Ph. D. in Electrical Engineering" and phd["anio"] == 2009
    assert {"organizacion": "Microsoft Research", "rol": "Research Intern", "desde": "May 2005"}.items() <= out[
        "afiliacion"
    ][1].items()
    assert {"otorgante": "IEEE", "anio": 2019}.items() <= out["distincion"][0].items()
    assert len(out["actividad"]) == 3 and out["actividad"][0]["tipo_actividad"] == "charla"
    assert len(out["link"]) > 30


def test_publicaciones():
    out = run_parse(
        JorgeSilvaSpider().parse_publicaciones(fixture_response("silva_publications.html", PUBLICACIONES, P))
    )
    pubs = out["publicacion"]
    assert len(pubs) == 6
    assert pubs[0]["doi"] == "10.3390/e20090640" and pubs[0]["anio"] == 2018
    assert pubs[0]["autores"] == ["Jorge F. Silva", "Milan S. Derpich"]
    assert {p["tipo_publicacion"] for p in pubs} == {"Journal article", "Preprint"}


def test_cv():
    out = run_parse(JorgeSilvaSpider().parse_cv(fixture_response("silva_cv.pdf", CV, P, cls=Response)))
    assert out["persona"][0]["email"] == "josilva@ing.uchile.cl"

    phd = out["formacion"][0]
    assert phd["institucion"] == "University of Southern California" and phd["anio"] == 2008
    assert phd["titulo_tesis"].startswith("On Optimal Signal Representation for Statistical Learning")
    assert len(out["formacion"]) == 4

    assert {"organizacion": "Universidad de Chile", "desde": "March 2015", "hasta": "present"}.items() <= out[
        "afiliacion"
    ][0].items()
    assert out["afiliacion"][0]["rol"] == "Associate Professor, Department of Electrical Engineering"

    dist = out["distincion"]
    assert len(dist) == 9 and dist[0]["nombre"] == "Elevation to the grade of IEEE Senior member"
    assert dist[0]["otorgante"] == "IEEE Advancement Committee" and dist[0]["anio"] == 2019

    proy = {p["codigo"]: p for p in out["proyecto"]}
    assert len(out["proyecto"]) == 13
    p = proy["1170854"]
    assert p["titulo"].startswith("Topics on Information and Decision with Applications")
    assert (p["fuente"], p["rol"], p["anio_inicio"], p["anio_fin"]) == (
        "Fondecyt Regular Grant",
        "Principal Investigator",
        2017,
        2021,
    )
    assert proy["1170044"]["investigador_responsable"] == "Marcos E. Orchard"
    assert proy["1171059"]["rol"] == "Co-investigator (Co-PI)"
    assert (
        proy["14IDL4-30327"]["fuente"] == "CORFO" and proy["14IDL4-30327"]["investigador_responsable"] == "Diana Comte"
    )
    assert proy["ACT1405"]["titulo"].startswith("Procesos fundamentales")

    act = out["actividad"]
    editorial = [a for a in act if a["tipo_actividad"] == "editorial"]
    assert editorial[0]["evento"] == "IEEE Transactions on Signal Processing"
    revisor = {a["titulo"] for a in act if a["tipo_actividad"] == "revisor"}
    assert len(revisor) == 10 and "ELSEVIER Computer, Speech and Language" in revisor
    assert sum(a["tipo_actividad"] == "charla" for a in act) >= 15

    pubs = out["publicacion"]
    tipos = [p["tipo_publicacion"] for p in pubs]
    assert tipos.count("International Journals") == 35 and tipos.count("International Conferences") == 41
    assert sum(p["estado"] == "under review" for p in pubs) == 3
    well = next(p for p in pubs if p["titulo"].startswith("Well Placement Strategies"))
    assert (
        well["doi"] == "10.1007/s11004-018-09777-2"
        and well["anio"] == 2019
        and well["venue"] == "Mathematical Geosciences"
    )
    lp = next(p for p in pubs if "Compressible Ergodic Processes" in p["titulo"])
    assert lp["autores"] == ["Jorge F. Silva", "Milan S. Derpich"] and lp["anio"] == 2015
    assert lp["venue"] == "IEEE Transactions on Signal Processing"

    assert [p["nombre"] for p in out["producto"]][1] == "Speech Index Pruning"
    it = [d for d in out["dictacion"] if d["nombre_curso"] == "Information Theory"]
    assert {(d["anio"], d["semestre"]) for d in it} == {(2011, "Spring"), (2014, "Fall")}
    assert len(out["dictacion"]) == 16
