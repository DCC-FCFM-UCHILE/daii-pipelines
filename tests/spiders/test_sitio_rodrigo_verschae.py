from conftest import fixture_response, run_parse

from daii.bronze.spiders.sites.rodrigo_verschae import RodrigoVerschaeSpider

URL = "https://rodrigo.verschae.org/"
P = "rodrigo-verschae"


def parse(fixture: str, path: str, callback: str) -> dict[str, list[dict]]:
    spider = RodrigoVerschaeSpider()
    return run_parse(getattr(spider, callback)(fixture_response(fixture, URL + path, P)))


def test_home():
    out = parse("verschae_home.html", "", "parse_home")
    p = out["persona"][0]
    assert p["nombre"] == "Rodrigo Verschae" and p["email"] == "rodrigo@verschae.org"
    orcid = next(x for x in out["perfil"] if x["plataforma"] == "orcid")
    assert orcid["identificador"] == "0000-0002-1661-3309"
    assert len(out["perfil"]) >= 5

    afil = {(a["organizacion"], a["rol"]): a for a in out["afiliacion"]}
    assert afil[("IDIA", "Faculty")]["url_organizacion"] == "https://idia.uchile.cl/"
    uoh = afil[("Institute of Engineering Sciences, Universidad de O’Higgins, Chile", "associate professor")]
    assert (uoh["desde"], uoh["hasta"]) == ("2018", "2026")
    utfsm = afil[("Department of Informatics, Universidad Tecnica Federico Santa Maria, Chile", "Associate Professor")]
    assert utfsm["desde"] == "2026"
    assert afil[("Fraunhofer IPK-Institute, Berlin, Germany", "associated researcher")]["hasta"] == "2005"
    assert len(out["afiliacion"]) >= 10

    grados = {f["grado"]: f for f in out["formacion"]}
    assert grados["Doctoral degree in Electrical Engineering"]["anio"] == 2010
    assert grados["M.Sc. in Applied Mathematics"]["institucion"] == "Ecole Normale Superieure (ENS) de Cachan, France"
    assert len(out["formacion"]) == 4

    d = out["distincion"][0]
    assert d["anio"] == 2025 and d["otorgante"] == "Institute of Engineers of Chile"


def test_publications():
    out = parse("verschae_publications.html", "publications/", "parse_publications")
    pubs = out["publicacion"]
    assert len(pubs) >= 60
    ev = next(
        x for x in pubs if x["url_destino"].startswith("https://www.sciencedirect.com/science/article/abs/pii/S0925")
    )
    assert ev["venue"] == "Neurocomputing" and ev["anio"] == 2026 and ev["tipo_publicacion"] == "Journal Articles"
    assert ev["autores"] == ["R Verschae", "I. Bugueno-Cordova"]
    assert {x["tipo_publicacion"] for x in pubs} == {"Journal Articles", "Conference Papers"}
    talk = out["actividad"][0]
    assert talk["tipo_actividad"] == "tutorial" and talk["fecha"] == "February 16, 2026"
    assert talk["evento"] == "FG2026" and talk["url_destino"].startswith("https://rodrigo.verschae.org/")


def test_research_y_news():
    out = parse("verschae_research.html", "research/", "parse_research")
    assert {"Smart Agriculture", "Event-Based Vision", "Field Robotics"} <= {a["nombre"] for a in out["area"]}
    fondef = next(x for x in out["proyecto"] if x["codigo"] == "IT23I0012")
    assert fondef["rol"] == "Director(alternate)" and fondef["titulo"].startswith("Pedagogical management system")
    assert len(out["proyecto"]) == 3

    out = parse("verschae_news.html", "news/", "parse_news")
    acts = out["actividad"]
    assert len(acts) >= 20
    assert not any("paper" in a["descripcion"].lower() for a in acts)
    román = next(a for a in acts if a["descripcion"] == "Organizing Committee")
    assert román["tipo_actividad"] == "organizacion_evento"
    assert román["fecha"] == "2026" and román["url_destino"] == "https://ro-man2026.org/"
    tipos = {a["descripcion"]: a["tipo_actividad"] for a in acts}
    assert tipos["New Visit"] == "visita" and tipos["Invited Speaker"] == "charla" and tipos["July 2019"] == "noticia"
