from conftest import fixture_response, run_parse

from daii.bronze.spiders.sites.marcos_orchard import MarcosOrchardSpider

SITIO = "https://www.morchard.cl/"
P = "marcos-orchard"


def parse(fixture: str, slug: str, callback: str) -> dict[str, list[dict]]:
    spider = MarcosOrchardSpider()
    return run_parse(getattr(spider, callback)(fixture_response(fixture, f"{SITIO}{slug}", P)))


def test_home():
    out = parse("orchard_home.html", "", "parse")
    p = out["persona"][0]
    assert p["nombre"] == "Dr. MARCOS E. ORCHARD" and p["cargo"] == "Professor"
    assert p["email"] == "morchard@ing.uchile.cl"
    assert p["bio"].startswith("Dr. Marcos E. Orchard is Professor")
    assert out["perfil"][0]["identificador"] == "H-4418-2013"

    afil = {a["rol"]: a for a in out["afiliacion"]}
    assert len(afil) == 6
    assert afil["Director"]["organizacion"] == "Centro de Aceleración Sostenible de Electromovilidad (CASE)"
    assert afil["Director"]["url_organizacion"] == "https://centroelectromovilidad.cl/"
    assert afil["Principal Investigator"]["organizacion"] == "Advanced Center for Electrical and Electronic Engineering"
    assert afil["Past-President"]["organizacion"] == "Chilean Association of Automatic Control (ACCA)"

    (ed,) = out["actividad"]
    assert ed["tipo_actividad"] == "editorial" and ed["rol"] == "Editor-in-Chief"
    assert ed["titulo"] == "International Journal of Prognostic and Health Management"
    # el menú queda fuera de related(region=...)
    assert not any("about-me" in link["url_destino"] for link in out.get("link", []))


def test_about():
    out = parse("orchard_about-me.html", "about-me/", "parse_about")
    assert len(out["area"]) == 3
    assert out["area"][0]["nombre"] == "Failure Prognosis in Nonlinear Dynamic Systems: Theory and Practice"
    phd = out["formacion"][0]
    assert phd == phd | {
        "grado": "PhD Electrical Engineering",
        "institucion": "Georgia Institute of Technology",
        "anio": 2007,
    }
    assert len(out["formacion"]) == 4


def test_research():
    out = parse("orchard_research-experience.html", "research-experience/", "parse_research")
    assert len(out["proyecto"]) >= 35
    f = next(x for x in out["proyecto"] if x["codigo"] == "1250036")
    assert f["fuente"] == "FONDECYT Project" and f["rol"] == "PI" and (f["anio_inicio"], f["anio_fin"]) == (2025, 2028)
    assert f["titulo"].startswith("Multimodal Context-aware Prognostic Methods")
    co = next(x for x in out["proyecto"] if x["codigo"] == "1250098")
    assert co["rol"] == "Co-PI" and co["investigador_responsable"] == "Jorge Silva (U.Ch)"
    case = next(x for x in out["proyecto"] if x["codigo"] == "20CTEM 131733")
    assert case["titulo"] == "Centro de Aceleración Sostenible de Electromovilidad (CASE)" and case["rol"] == "Director"
    redes = next(x for x in out["proyecto"] if x["codigo"] == "REDES-170031")  # sin comillas en la fuente
    assert redes["titulo"] == "Prognostics and Health Management in Electro-mobility"


def test_awards():
    out = parse("orchard_awards-distinctions.html", "awards-distinctions/", "parse_awards")
    assert len(out["distincion"]) >= 14
    d = out["distincion"][0]
    assert (d["nombre"], d["otorgante"], d["anio"]) == (
        "Best Paper Award",
        "Annual Conference of the PHM Society 2025",
        2025,
    )
    fellow = next(x for x in out["distincion"] if x["nombre"] == "PHM Society Fellow")
    assert fellow["anio"] == 2018


def test_publications():
    out = parse("orchard_journal-publications.html", "journal-publications/", "parse_publications")
    pubs = out["publicacion"]
    assert len(pubs) >= 110
    p = pubs[0]
    assert p["titulo"].startswith("Coordinated production and charging strategies")
    assert p["venue"] == "International Journal of Mining, Reclamation and Environment" and p["anio"] == 2026
    assert p["doi"] == "10.1080/17480930.2026.2748651" and p["tipo_publicacion"] == "Journal Publications"
    assert "Orchard, M." in p["autores"] and p["autores"][0] == "Flores-Quiroz, A."

    conf = parse("orchard_conference-articles.html", "conference-articles/", "parse_publications")["publicacion"]
    assert len(conf) >= 90
    assert (
        conf[0]["venue"] == "9th European Conference of the Prognostics and Health Management Society 2026 – PHME 2026"
    )
    assert (
        conf[0]["titulo"]
        == "Trolley-Assisted Charging for Full-Shift Operation of Battery-Electric LHDs in Underground Mining"
    )

    books = parse("orchard_books-books-chapters.html", "books-books-chapters/", "parse_publications")["publicacion"]
    assert len(books) == 7
    ch = books[4]
    assert (ch["titulo"], ch["venue"], ch["anio"]) == (
        "Prognosis",
        "Integrated Vehicle Management, The Technology",
        2013,
    )


def test_teaching():
    out = parse("orchard_teaching.html", "teaching/", "parse_teaching")
    cursos = {d["codigo_curso"]: d["nombre_curso"] for d in out["dictacion"]}
    assert len(cursos) == 11
    assert cursos["EL5205"] == "Laboratorio de Control Avanzado"
    assert cursos["EL7014"] == "Diagnóstico y Pronóstico de Fallas"
    assert cursos["ECE 4562"] == "Neural Networks and Fuzzy Logic in Control"


def test_dissemination():
    out = parse("orchard_dissemination-and-transfer.html", "dissemination-and-transfer/", "parse_dissemination")
    acts = out["actividad"]
    assert len(acts) == 9
    assert acts[0] == acts[0] | {"tipo_actividad": "keynote", "rol": "Keynote Speaker"}
    assert acts[0]["titulo"].startswith("Congreso Nacional de Control Automático 2021")
    acca = next(a for a in acts if a["titulo"] == "Fault Diagnosis for Reconfigurable Control")
    assert acca["evento"] == "XVIII Congreso de la Asociación Chilena de Control Automático"
