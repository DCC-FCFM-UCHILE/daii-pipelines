from conftest import fixture_response, run_parse

from daii.bronze.spiders.sites.claudia_lopez import ClaudiaLopezSpider

URL = "https://claudialopezmoncada.com/"
P = "claudia-lopez"


def parse(fixture: str, path: str, callback: str) -> dict[str, list[dict]]:
    spider = ClaudiaLopezSpider()
    return run_parse(getattr(spider, callback)(fixture_response(fixture, URL + path, P)))


def test_home():
    out = parse("lopez_home.html", "", "parse_home")
    p = out["persona"][0]
    assert p["nombre"] == "Claudia López Moncada" and p["cargo"].startswith("Associate Professor, Department of")
    afil = {a["organizacion"]: a for a in out["afiliacion"]}
    assert afil["Department of Computer Science"]["rol"] == "Associate Professor"
    assert afil["National Center for Artificial Intelligence (CENIA)"]["rol"] == "principal investigator"
    assert afil["Millennium Institute on Authority and Social Regulation (ASOR)"]["rol"] == "associate investigator"
    utfsm = afil["Department of Informatics at Universidad Técnica Federico Santa María"]
    assert (utfsm["desde"], utfsm["hasta"]) == ("2015", "early 2026")
    cscw = next(a for a in out["actividad"] if a["evento"] == "ACM CSCW 2026")
    assert cscw["tipo_actividad"] == "comite_programa" and cscw["rol"] == "Senior Program Committee"
    dash = out["producto"][0]
    assert (
        dash["nombre"] == "dashAI"
        and dash["rol"] == "deputy director"
        and dash["url_destino"] == "https://www.dash-ai.com/"
    )


def test_bio():
    out = parse("lopez_bio.html", "bio/", "parse_bio")
    grados = {f["grado"]: f for f in out["formacion"]}
    assert (grados["B.Sc. in Informatics"]["institucion"], grados["B.Sc. in Informatics"]["anio"]) == ("UTFSM", 2004)
    assert grados["Ph.D. in Information Sciences and Technology"]["institucion"] == "U. of Pittsburgh"
    cenia = [a for a in out["afiliacion"] if a["organizacion"].startswith("National Center of Artificial Intelligence")]
    assert {(a["rol"], a["desde"], a["hasta"]) for a in cenia} == {
        ("Principal Investigator", "Mar. 2024", None),
        ("Associate Investigator", "2021", "2024"),
    }
    assert len(out["afiliacion"]) >= 6
    assert any(d["nombre"] == "Fulbright Ph.D. Scholarship" and d["anio"] == 2010 for d in out["distincion"])
    tipos = {a["tipo_actividad"] for a in out["actividad"]}
    assert {"politica_publica", "revisor", "comite_programa", "servicio", "charla"} <= tipos
    charla = next(a for a in out["actividad"] if a["descripcion"] == "Invited event participation")
    assert charla["tipo_actividad"] == "charla"


def test_publications():
    out = parse("lopez_publications.html", "publications/", "parse_publications")
    pubs = out["publicacion"]
    assert len(pubs) >= 65
    toit = next(x for x in pubs if x["titulo"].startswith("Behind the myths of citizen participation"))
    assert toit["anio"] == 2017 and toit["autores"] == ["López, C.", "Farzan, R.", "Lin, Y. R."]
    assert toit["venue"].startswith("ACM Transactions on Internet Technology (TOIT)")
    ijhcs = next(x for x in pubs if x["doi"] == "10.1016/j.ijhcs.2026.103769")
    assert ijhcs["tipo_publicacion"] == "Peer-reviewed journal articles" and ijhcs["anio"] == 2026
    lncs = next(
        x for x in pubs if x["titulo"] == "Towards adaptive recruitment and engagement mechanisms in social systems"
    )
    assert lncs["anio"] == 2012 and lncs["autores"] == ["C. López", "P. Brusilovsky"]


def test_students():
    out = parse("lopez_students.html", "students/", "parse_students")
    tesis = out["tesis"]
    assert len(tesis) >= 80
    t = next(x for x in tesis if x["estudiante"] == "Felipe González Pizarro")
    assert t["titulo"].startswith("TopicVisExplorer") and t["anio"] == 2021 and t["programa"] == "MII"
    adithya = next(x for x in tesis if x["estudiante"] == "Adithya Aggarwal")
    assert adithya["anio"] == 2016 and adithya["rol"] == "I have been part of the following graduate committees:"


def test_teaching_outreach_research():
    out = parse("lopez_teaching.html", "teaching/", "parse_teaching")
    hcai = next(d for d in out["dictacion"] if d["nombre_curso"] == "Human-centered AI")
    assert (hcai["anio"], hcai["semestre"]) == (2026, "Spring")
    topics = sorted(
        d["anio"] for d in out["dictacion"] if d["nombre_curso"] == "Topics in information systems research"
    )
    assert topics == [2016, 2017, 2022, 2023]

    out = parse("lopez_outreach.html", "outreach/", "parse_outreach")
    acts = out["actividad"]
    assert len(acts) >= 150
    assert {"asesoria", "prensa", "divulgacion", "charla"} <= {a["tipo_actividad"] for a in acts}
    assert {a["descripcion"] for a in acts if a["tipo_actividad"] == "charla"} == {
        "Invited academic talks",
        "Invited academic panels",
        "Guest lectures",
    }
    assert acts[0]["fecha"] == "2026" and acts[0]["titulo"].startswith("Invited expert to the Technical workshop")

    out = parse("lopez_research.html", "research/", "parse_research")
    assert out["area"][0]["nombre"] == "Human-centered artificial intelligence" and len(out["area"]) == 7
    proy = {x["titulo"]: x for x in out["proyecto"]}
    cenia = proy["Centro Nacional de Inteligencia Artificial (CENIA)"]
    assert (cenia["fuente"], cenia["anio_inicio"], cenia["rol"]) == ("Basal, ANID", 2021, "principal investigator")
    twitter = proy["Twitter and presidential leadership"]
    assert (twitter["anio_inicio"], twitter["anio_fin"], twitter["monto"], twitter["rol"]) == (
        2018,
        2019,
        "US$20,000",
        "PI",
    )
    assert len(out["proyecto"]) == 15
