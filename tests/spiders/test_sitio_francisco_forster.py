from conftest import fixture_response, run_parse
from scrapy.http import Response

from daii.bronze.spiders.sites.francisco_forster import CV, HOME, FranciscoForsterSpider

P = "francisco-forster"


def test_home():
    out = run_parse(FranciscoForsterSpider().parse(fixture_response("forster_home.html", HOME, P)))
    assert out["persona"][0]["nombre"] == "Francisco Förster Burón"

    af = {a["organizacion"]: a for a in out["afiliacion"]}
    assert af["Data and Artificial Intelligence Initiative (IDIA)"]["rol"] == "Full Professor"
    mas = af["Millennium Institute of Astrophysics (MAS)"]
    assert (mas["rol"], mas["desde"], mas["hasta"]) == ("director", "2024", None)
    alerce = af["Automatic Learning for the Rapid Classification of Events (ALeRCE)"]
    assert (alerce["rol"], alerce["desde"], alerce["hasta"]) == ("principal investigator", "2018", "2024")
    hits = af["High Cadence Transient Survey (HiTS)"]
    assert (hits["rol"], hits["desde"], hits["hasta"]) == ("principal investigator", "2012", "2018")
    assert af["Master of Data Science (MDS)"]["rol"] == "academic coordinator"
    assert {
        "Center for Mathematical Modelling (CMM)",
        "Center of Excellence in Astrophysics and Related Technologies (CATA)",
    } <= af.keys()

    prod = {p["nombre"]: p for p in out["producto"]}
    assert prod["ALeRCE"]["tipo_producto"] == "broker" and prod["ALeRCE"]["url_destino"] == "https://alerce.science/"
    assert set(prod) == {"ALeRCE", "HiTS", "CHASE"}

    assert {"grado": "Ph.D.", "institucion": "University of Oxford", "anio": 2009}.items() <= out["formacion"][
        0
    ].items()
    assert len(out["area"]) == 4 and out["area"][0]["nombre"] == "Time-Domain Astrophysics"
    orcid = next(p for p in out["perfil"] if p["plataforma"] == "orcid")
    assert orcid["identificador"] == "0000-0003-3459-2270"
    assert len(out["link"]) > 10


def test_cv():
    out = run_parse(FranciscoForsterSpider().parse_cv(fixture_response("forster_cv.pdf", CV, P, cls=Response)))

    dphil = out["formacion"][0]
    assert (dphil["grado"], dphil["institucion"], dphil["anio"]) == ("D.Phil. in Physics", "University of Oxford", 2009)
    assert dphil["titulo_tesis"] == "Understanding Type Ia Supernova Ignition Conditions Diversity"

    assert len(out["afiliacion"]) >= 10
    assert {"organizacion": "Millennium Institute for Astrophysics", "rol": "Director", "desde": "2024"}.items() <= out[
        "afiliacion"
    ][0].items()
    assert out["afiliacion"][-1]["rol"] == "Research Assistant with Prof. Simón Casassus"  # acentos LaTeX recompuestos

    proy = out["proyecto"]
    assert len(proy) == 11
    assert {
        "fuente": "Quimal",
        "rol": "Principal investigator",
        "anio_inicio": 2024,
        "monto": "206 kUSD",
    }.items() <= proy[0].items()
    fondecyt = next(p for p in proy if p["rol"] == "Fondecyt Initiation into Research Fellow")
    assert (fondecyt["anio_inicio"], fondecyt["anio_fin"]) == (2013, 2017)

    act = out["actividad"]
    assert sum(a["tipo_actividad"] == "charla_invitada" for a in act) == 15
    assert sum(a["tipo_actividad"] == "organizacion_evento" for a in act) == 4

    astro = [d for d in out["dictacion"] if d["nombre_curso"] == "Astroinformatics, U. Chile"]
    assert len(astro) == 16 and (astro[0]["anio"], astro[0]["semestre"]) == (2011, "B")

    tesis = out["tesis"]
    assert len(tesis) >= 50
    pena = next(t for t in tesis if t["estudiante"] == "José Peña")
    assert (pena["nivel"], pena["rol"], pena["programa"]) == ("Ph.D.", "co-supervisor", "Astronomy")

    assert any(d["nombre"].startswith("Beca Irma Salas") and d["anio"] == 1998 for d in out["distincion"])
    assert out["producto"][0]["nombre"] == "Flair"
