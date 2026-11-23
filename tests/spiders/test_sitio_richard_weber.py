from conftest import fixture_response, run_parse

from daii.raw.spiders.sites.richard_weber import RichardWeberSpider

SITIO = "https://richardweber.wixsite.com/home"
P = "richard-weber"


def parse(fixture: str, path: str, callback: str) -> dict[str, list[dict]]:
    spider = RichardWeberSpider()
    return run_parse(getattr(spider, callback)(fixture_response(fixture, f"{SITIO}{path}", P)))


def test_home():
    out = parse("weber_home.html", "", "parse")
    p = out["persona"][0]
    assert p["nombre"] == "RICHARD WEBER" and p["cargo"] == "Professor"
    assert p["bio"].startswith("I am Associate Professor at the Department of Industrial Engineering")

    perfiles = {x["plataforma"]: x for x in out["perfil"]}
    assert {"orcid", "dblp", "scholar", "researchgate", "researcherid", "linkedin"} <= perfiles.keys()
    assert perfiles["orcid"]["identificador"] == "0000-0002-6351-1065"
    assert perfiles["researcherid"]["identificador"] == "A-9491-2009"

    afil = {a["rol"]: a["organizacion"] for a in out["afiliacion"]}
    assert afil["Associate Professor"] == "Department of Industrial Engineering"
    assert afil["Director"].startswith("Graduate School of the Faculty of Physical and Mathematical Sciences")
    assert afil["head"] == "Data Science group within the Institute Complex Engineering Systems"

    act = {a["rol"]: a for a in out["actividad"]}
    assert act["Associate Editor"] == act["Associate Editor"] | {
        "tipo_actividad": "editorial",
        "titulo": "journal Applied Soft Computing",
    }
    assert act["Chairman of the Program Committee"]["tipo_actividad"] == "comite_programa"
    assert [a["nombre"] for a in out["area"]] == [
        "data mining",
        "dynamic data mining",
        "data science",
        "social network analysis",
    ]
    # header (menú, redes) y footer fuera de related(region=...)
    assert not any("wixsite.com" in x["url_destino"] or "wix.com" in x["url_destino"] for x in out["link"])
    assert any("isci.cl" in x["url_destino"] for x in out["link"])


def test_cv():
    out = parse("weber_cv.html", "/cv", "parse_cv")
    assert [(f["anio"], f["grado"]) for f in out["formacion"]] == [
        (1986, "Diploma in Mathematics"),
        (1988, "M.Sc. Operations Research"),
        (1992, "PhD Operations Research"),
    ]
    assert out["formacion"][2]["institucion"] == "RWTH Aachen University, Aachen, Germany"

    dir_ = out["afiliacion"][0]
    assert dir_ == dir_ | {
        "rol": "Director Graduate School",
        "organizacion": "Faculty of Physical Sciences and Mathematics, Universidad de Chile",
        "desde": "08/2014",
        "hasta": "present",
    }
    assert {"rol": "Professor", "desde": "1999"}.items() <= out["afiliacion"][1].items()

    assert len(out["actividad"]) == 5 and all(a["tipo_actividad"] == "visita" for a in out["actividad"])
    leuven = out["actividad"][0]
    assert leuven["fecha"] == "02-05/2013" and leuven["titulo"].startswith("Visiting Professor KU Leuven, Belgium")


def test_publications():
    out = parse("weber_publications.html", "/publications", "parse_publications")
    pubs = out["publicacion"]
    assert len(pubs) >= 120
    first = pubs[0]
    assert first == first | {
        "titulo": "Fifty Years of Information Sciences: A Bibliometric Overview",
        "venue": "Information Sciences 432, 245–268",
        "anio": 2018,
        "doi": "10.1016/j.ins.2017.11.054",
        "tipo_publicacion": "JOURNAL ARTICLES",
        "autores": ["Merigó, J. M.", "Pedrycz, W.", "Weber, R.", "de la Sotta, C."],
    }
    tipos = {p["tipo_publicacion"] for p in pubs}
    assert tipos == {"JOURNAL ARTICLES", "BOOKS", "BOOK CHAPTERS", "CONFERENCE PROCEEDINGS"}
    thesis = next(p for p in pubs if p["titulo"].startswith("Entwicklung und Anwendung"))
    assert thesis["anio"] == 1992 and thesis["autores"] == ["Weber, R."] and thesis["tipo_publicacion"] == "BOOKS"


def test_projects():
    out = parse("weber_projects.html", "/projects", "parse_projects")
    proys = out["proyecto"]
    assert len(proys) == 36
    f = next(x for x in proys if x["codigo"] == "1181036")
    assert f == f | {
        "titulo": "Dynamic clustering using Evolving Features",
        "fuente": "Fondecyt project 1181036",
        "rol": "Principal Investigator",
        "monto": "USD125,000 approx.",
        "anio_inicio": 2018,
        "anio_fin": 2022,
    }
    basal = next(x for x in proys if x["codigo"] == "FB016")
    assert basal["titulo"] == "Complex Engineering Systems Institute" and basal["rol"] == "Principal co-Investigator"
    lan = next(x for x in proys if x["titulo"] == "Development of Predictive Models for an Airline")
    assert lan["fuente"] == "LAN Chile" and (lan["anio_inicio"], lan["anio_fin"]) == (2004, 2005)
