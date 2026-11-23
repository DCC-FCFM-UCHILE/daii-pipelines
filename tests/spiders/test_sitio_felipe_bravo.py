from conftest import fixture_response, run_parse

from daii.raw.spiders.sites.felipe_bravo import FelipeBravoSpider

SITIO = "https://felipebravom.com/"
P = "felipe-bravo"


def test_home():
    out = run_parse(FelipeBravoSpider().parse_home(fixture_response("bravo_home.html", SITIO, P)))
    p = out["persona"][0]
    assert p["nombre"] == "Felipe Bravo-Marquez" and p["telefono"] == "+56 2 2978 4974"
    assert len(out["afiliacion"]) >= 6
    cenia = next(a for a in out["afiliacion"] if "CENIA" in a["organizacion"])
    assert cenia["rol"] == "Principal Researcher" and cenia["url_organizacion"] == "https://www.cenia.cl"
    assert "Natural language processing" in {a["nombre"] for a in out["area"]}
    perfiles = {x["plataforma"]: x["url_destino"] for x in out["perfil"]}
    assert perfiles["orcid"] == "https://orcid.org/0000-0002-2153-4306" and "dblp" in perfiles
    nlp = next(d for d in out["dictacion"] if d["codigo_curso"] == "CC6205")
    assert nlp["nombre_curso"] == "Natural Language Processing" and nlp["url_curso"].startswith("https://github.com")


def test_cv():
    out = run_parse(FelipeBravoSpider().parse_cv(fixture_response("bravo_cv.html", SITIO + "cv/", P)))
    assert {"grado": "PhD. Computer Science", "institucion": "University of Waikato", "anio": 2017}.items() <= out[
        "formacion"
    ][0].items()
    yahoo = next(a for a in out["afiliacion"] if a["organizacion"].startswith("Yahoo"))
    assert yahoo["rol"] == "Research Engineer" and (yahoo["desde"], yahoo["hasta"]) == ("2011", "2013")
    cc6104 = [d for d in out["dictacion"] if d["codigo_curso"] == "CC6104"]
    assert len(cc6104) == 5 and cc6104[0]["anio"] == 2025 and cc6104[0]["semestre"] == "spring"
    assert len(out["dictacion"]) > 30
    fondecyt = next(x for x in out["proyecto"] if x["codigo"] == "11200290")
    assert fondecyt["titulo"] == "Tracking social public opinion: a stream-mining based approach"
    assert fondecyt["fuente"] == "FONDECYT de Iniciación"
    assert (fondecyt["anio_inicio"], fondecyt["anio_fin"]) == (2020, 2023)
    assert any(d["nombre"].startswith("TWAS-LACREP") and d["anio"] == 2022 for d in out["distincion"])
    villena = next(t for t in out["tesis"] if t["estudiante"] == "Fabián Villena")
    assert villena["nivel"] == "PhD" and villena["anio"] == 2026
    assert villena["rol"] == "Co-supervised with Jocelyn Dunstan"
    assert len(out["tesis"]) > 40
    tipos = {a["tipo_actividad"] for a in out["actividad"]}
    assert {"charla", "prensa", "servicio"} <= tipos and len(out["actividad"]) > 100
    assert out["producto"][0]["url_destino"] == "https://www.dash-ai.com/"


def test_publicaciones():
    resp = fixture_response("bravo_publications.html", SITIO + "publications/", P)
    pubs = run_parse(FelipeBravoSpider().parse_publicaciones(resp))["publicacion"]
    assert len(pubs) > 70
    p = pubs[0]
    assert p["titulo"] == "Quantifying Social Biases in Language Model Classifiers is Domain-Dependent"
    assert p["doi"] == "10.1145/3834859" and p["anio"] == 2026 and p["tipo_publicacion"] == "Journal Papers"
    assert p["autores"] == ["T. Quiroga", "F. Bravo-Marquez", "V. Barriere"]
    assert any(x["estado"] == "to appear" for x in pubs)
    assert sum(1 for x in pubs if x["doi"]) > 20
