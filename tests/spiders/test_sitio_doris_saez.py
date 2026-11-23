import pytest
from conftest import FIXTURES, fixture_response, run_parse
from scrapy.http import Response

from daii.raw.spiders.sites.doris_saez import BASE, PROJECTS, PUBLICATIONS, STUDENTS, TEACHING, DorisSaezSpider

P = "doris-saez"
CV = BASE + "wp-content/uploads/2025/08/CV_DSaez_Aug_2025.pdf"


def test_home():
    out = run_parse(DorisSaezSpider().parse(fixture_response("saez_home.html", BASE, P)))
    p = out["persona"][0]
    assert (p["nombre"], p["cargo"], p["email"]) == ("Doris Sáez Hueichapan", "Full Professor", "dsaez@ing.uchile.cl")
    assert "Sub-directorate of Indigenous People" in {a["organizacion"] for a in out["afiliacion"]}
    vinc = {a["titulo"]: a["url_destino"] for a in out["actividad"] if a["tipo_actividad"] == "vinculacion"}
    assert vinc["Mapuche Communities"] == "http://www.comunidadesmapuchefcfm.cl"
    assert "Collaborative work with Indigenous communities" in vinc and "Kimeltuwe Lof Tech Project" in vinc
    assert "SHORE Project" not in vinc  # proyecto, no vinculación
    assert any(link["url_destino"] == "https://www.shore.cl/" for link in out["link"])


def test_publications():
    pubs = run_parse(DorisSaezSpider().parse_publications(fixture_response("saez_publications.html", PUBLICATIONS, P)))[
        "publicacion"
    ]
    assert len(pubs) >= 160
    p = next(x for x in pubs if x["titulo"] == "Evolving Fuzzy Prediction Intervals in Nonstationary Environments")
    assert (p["anio"], p["doi"], p["tipo_publicacion"]) == (2024, "10.1109/TETCI.2023.3296486", "ISI JOURNAL ARTICLES")
    assert p["venue"] == "IEEE Transactions on Emerging Topics in Computational Intelligence"
    assert p["autores"] == ["O. Cartagena", "F. Trovò", "M. Roveri", "D. Sáez"]
    assert {x["tipo_publicacion"] for x in pubs} == {
        "BOOKS & BOOKS CHAPTERS",
        "ISI JOURNAL ARTICLES",
        "OTHER JOURNALS",
        "CONFERENCES",
    }


def test_projects():
    ps = run_parse(DorisSaezSpider().parse_projects(fixture_response("saez_projects.html", PROJECTS, P)))["proyecto"]
    assert len(ps) == 37
    m = next(x for x in ps if x["codigo"] == "14I10063")
    assert m["titulo"] == "Design and Implementation of an Experimental Prototype of Microgrid for Mapuche Communities"
    assert (m["fuente"], m["rol"], m["anio_inicio"], m["anio_fin"]) == ("Project FONDEF IDeA", "Director", 2015, 2016)
    assert next(x for x in ps if x["codigo"] == "1220507")["rol"] == "Principal Investigator"


def test_students():
    ts = run_parse(DorisSaezSpider().parse_students(fixture_response("saez_students.html", STUDENTS, P)))["tesis"]
    assert len(ts) >= 70
    t = next(x for x in ts if x["estudiante"] == "Claudio Zúñiga")
    assert (t["titulo"], t["anio"], t["programa"], t["estado"]) == (
        "A Water-Energy-Food Management System Based on Reinforcement Learning Algorithms",
        2025,
        "Master in Electrical Engineering, U. Chile",
        "Former Students",
    )
    assert sum(x["estado"] == "Current Students" for x in ts) == 9


def test_teaching():
    ds = run_parse(DorisSaezSpider().parse_teaching(fixture_response("saez_teaching.html", TEACHING, P)))["dictacion"]
    assert {d["codigo_curso"]: d["nombre_curso"] for d in ds}["EL7012"] == "Intelligent Control" and len(ds) == 6


# El CV trae RUT y fecha de nacimiento en texto no editable: no se versiona (ver .gitignore).
# Para correr este test: curl -sLo tests/fixtures/saez_cv.pdf <perfiles.cv de doris-saez en config/academicos.yaml>
@pytest.mark.skipif(not (FIXTURES / "saez_cv.pdf").exists(), reason="fixture con datos sensibles, no versionado")
def test_cv():
    out = run_parse(DorisSaezSpider().parse_cv(fixture_response("saez_cv.pdf", CV, P, cls=Response)))
    assert out["formacion"][0] == {**out["formacion"][0], "grado": "Doctor in Engineering Sciences", "anio": 2000}
    assert (
        out["formacion"][0]["institucion"] == "Pontificia Universidad Católica de Chile" and len(out["formacion"]) == 4
    )
    sub = next(a for a in out["afiliacion"] if a["rol"] == "Founding Member")
    assert sub["organizacion"].startswith("Sub-directorate of Indigenous People") and sub["desde"] == "2019"
    assert {"rol": "Chair", "organizacion": "IEEE Chile Section", "desde": "2007"}.items() <= next(
        a for a in out["afiliacion"] if a["organizacion"] == "IEEE Chile Section" and a["rol"] == "Chair"
    ).items()
    assert {a["titulo"] for a in out["actividad"]} >= {"IEEE Transactions on Smart Grid", "Soft Computing"}
    d = next(x for x in out["distincion"] if x["anio"] == 2009)
    assert d["nombre"] == "MGA-IEEE Achievement Award"
    assert any(x["otorgante"] == "Ministry of Energy" for x in out["distincion"])
    # datos sensibles de la cabecera del CV no se extraen
    assert "8.952" not in str(out) and "1971" not in str(out)
