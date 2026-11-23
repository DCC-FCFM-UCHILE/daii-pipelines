from conftest import fixture_response, run_parse
from scrapy.http import Response

from daii.bronze.spiders.sites.sebastian_ferrada import SebastianFerradaSpider

URL = "https://sferrada.com/"
P = "sebastian-ferrada"


def parse(fixture: str, path: str, callback: str, cls=None) -> dict[str, list[dict]]:
    spider = SebastianFerradaSpider()
    kw = {"cls": cls} if cls else {}
    return run_parse(getattr(spider, callback)(fixture_response(fixture, URL + path, P, **kw)))


def test_home():
    out = parse("ferrada_home.html", "", "parse_home")
    p = out["persona"][0]
    assert p["nombre"] == "Sebastián Ferrada" and p["cargo"] == "Assistant Professor"
    assert p["bio"].startswith("I’m Sebastián, an Assistant Professor")
    assert {x["plataforma"] for x in out["perfil"]} >= {"scholar", "github", "twitter", "portafolio"}

    afil = {a["organizacion"]: a for a in out["afiliacion"]}
    assert afil["Data & Artificial Intelligence Initiative"]["rol"] == "Assistant Professor"
    assert afil["Data & Artificial Intelligence Initiative"]["url_organizacion"] == "http://idia.uchile.cl"
    assert afil["Department of Computer Science at Universidad de Chile"]["rol"] == "Assistant Professor"
    assert afil["Institute for Foundational Research on Data (IMFD)"]["rol"] == "Junior Researcher"
    cenia = afil["National Center for Artificial Intelligence Research (CENIA)"]
    assert cenia["rol"] == "Collaborating Researcher" and cenia["url_organizacion"] == "http://cenia.cl"

    assert "Graph Databases and Knowledge Graphs" in {a["nombre"] for a in out["area"]}
    phd = next(f for f in out["formacion"] if f["grado"] == "PhD in Computer Science")
    assert phd["anio"] == 2021 and phd["institucion"] == "Universidad de Chile"
    assert len(out["formacion"]) == 3


def test_listados_siguen_detalles():
    spider = SebastianFerradaSpider()
    pubs = list(spider.parse_publicaciones(fixture_response("ferrada_publication.html", URL + "publication/", P)))
    detalles = [r.url for r in pubs if not isinstance(r, dict) and r.callback == spider.parse_publicacion]
    assert len(detalles) == 24 and URL + "publication/2024-sw-ferrada-simjoin/" in detalles
    talks = list(spider.parse_charlas(fixture_response("ferrada_event.html", URL + "event/", P)))
    assert sum(1 for r in talks if not isinstance(r, dict) and r.callback == spider.parse_charla) >= 10


def test_publicacion():
    out = parse("ferrada_publication_detail.html", "publication/2024-sw-ferrada-simjoin/", "parse_publicacion")
    pub = out["publicacion"][0]
    assert pub["titulo"] == "Similarity joins and clustering for SPARQL"
    assert pub["anio"] == 2024 and pub["venue"] == "Semantic Web Journal"
    assert pub["tipo_publicacion"] == "Journal article"
    assert pub["autores"] == ["Sebastián Ferrada", "Aidan Hogan", "Benjamin Bustos"]
    assert pub["url_destino"].endswith("2024-SW-ferrada-simjoin.pdf")


def test_charla():
    out = parse("ferrada_talk.html", "talk/modern-graphs-for-modern-apps/", "parse_charla")
    t = out["actividad"][0]
    assert t["titulo"] == "Modern Graphs for Modern Apps"
    assert t["evento"] == "Invited talk at Universidad Politécnica de Madrid"
    assert (t["fecha"], t["descripcion"]) == ("Mar 4, 2026", "Madrid, Spain")


def test_proyectos_premios_noticias_prensa():
    proy = parse("ferrada_project.html", "project/", "parse_proyectos")["proyecto"]
    fondecyt = next(p for p in proy if p["titulo"] == "Knowledge Graph Extraction from Tabular Sources")
    assert fondecyt["anio_inicio"] == 2025 and fondecyt["fuente"].startswith("Fondecyt Iniciación 2025")

    premios = parse("ferrada_promotion.html", "promotion/", "parse_premios")["distincion"]
    coopis = next(d for d in premios if d["nombre"] == "Best Paper Award")
    assert coopis["anio"] == 2023 and "Cooperative Information Systems" in coopis["otorgante"]
    assert len(premios) == 5

    noticias = parse("ferrada_news.html", "news/", "parse_noticias")["actividad"]
    fondef = next(n for n in noticias if n["titulo"] == "Fondef IDeA I+D adjudicated")
    assert fondef["fecha"] == "Jun 8, 2026" and "comunicaciones.dcc.uchile.cl" in fondef["url_destino"]
    assert not any("paper" in n["titulo"].lower() for n in noticias)

    prensa = parse("ferrada_press.html", "press/", "parse_noticias")["actividad"]
    dinamo = next(n for n in prensa if n["titulo"].startswith("La batalla por los data centers"))
    assert dinamo["evento"] == "El Dínamo" and dinamo["fecha"] == "Nov 13, 2026"
    assert dinamo["descripcion"].startswith("El Dínamo. Feature by Francisco Rosales")
    assert len(prensa) >= 10


def test_cv():
    out = parse("ferrada_cv.pdf", "uploads/resume.pdf", "parse_cv", cls=Response)
    phd = next(f for f in out["formacion"] if f["grado"] == "Ph.D. in Computer Science")
    assert phd["titulo_tesis"] == "Similarity-based Web Queries" and phd["anio"] == 2021

    idia = next(a for a in out["afiliacion"] if a["organizacion"].startswith("Data & Artificial Intelligence"))
    assert (idia["rol"], idia["desde"], idia["hasta"]) == ("Assistant Professor", "2024", None)
    lin = next(a for a in out["afiliacion"] if "Linköping" in a["organizacion"])
    assert (lin["desde"], lin["hasta"]) == ("2021", "2023")

    proy = {p["titulo"]: p for p in out["proyecto"]}
    kg = proy["Knowledge Graph Extraction from Tabular Sources"]
    assert (kg["codigo"], kg["rol"]) == ("11251322", "Principal Investigator")
    assert (kg["anio_inicio"], kg["anio_fin"]) == (2025, 2027)
    vr = proy["Interoperability and Integration of Graph Database Models"]
    assert vr["codigo"] == "2019-056" and vr["investigador_responsable"] == "Olaf Hartig"

    assert {d["nombre"] for d in out["distincion"]} >= {"Outstanding PC Member", "Best Graduate"}
    act = out["actividad"]
    tgdk = next(a for a in act if a["tipo_actividad"] == "editorial")
    assert tgdk["evento"] == "Transactions on Graph Data and Knowledge (TGDK)" and tgdk["fecha"] == "Since 2023"
    kcap = next(a for a in act if a["evento"] == "13th International Conference on Knowledge Capture")
    assert kcap["tipo_actividad"] == "organizacion_evento" and kcap["rol"] == "Program Co-Chair"
    assert sum(a["tipo_actividad"] == "comite_programa" for a in act) >= 10

    tesis = {t["estudiante"]: t for t in out["tesis"]}
    assert tesis["Benito Fuentes"]["titulo"] == "Implementation of Algorithms for Graph Analytics in Secondary Memory"
    assert tesis["Benito Fuentes"]["estado"] == "Ongoing"
    assert tesis["Matías López"]["anio"] == 2024 and tesis["Matías López"]["nivel"] == "Undergraduate Students"
    assert len(out["tesis"]) == 14

    ir = next(d for d in out["dictacion"] if d["nombre_curso"] == "Information Retrieval")
    assert ir["institucion"] == "U. de Chile" and ir["rol"] == "Lecturer (profesor de cátedra)"
    assert len(out["dictacion"]) >= 18
