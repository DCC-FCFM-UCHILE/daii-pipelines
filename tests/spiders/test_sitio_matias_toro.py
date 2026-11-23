from conftest import fixture_response, run_parse

from daii.raw.spiders.sites.matias_toro import MatiasToroSpider


def test_home():
    resp = fixture_response("toro_home.html", "https://matiastoro.github.io/", "matias-toro")
    out = run_parse(MatiasToroSpider().parse_home(resp))

    p = out["persona"][0]
    assert p["nombre"] == "Matías Toro" and p["cargo"] == "Assistant Professor" and p["email"] == "mtoro@dcc.uchile.cl"
    assert {x["plataforma"] for x in out["perfil"]} >= {"dblp", "orcid", "github"}
    assert out["afiliacion"][0]["organizacion"] == "Department of Computer Science, Universidad de Chile"
    imfd = [a for a in out["afiliacion"] if "IMFD" in a["organizacion"]]
    assert ("2022", "2025") in {(a["desde"], a["hasta"]) for a in imfd}
    assert {a["nombre"] for a in out["area"]} == {"Gradual typing", "Privacy and security", "Typed query languages"}
    phd = out["formacion"][0]
    assert phd["anio"] == 2019 and phd["titulo_tesis"] == "Abstracting Gradual Typing: Metatheory and Applications"

    pubs = out["publicacion"]
    assert len(pubs) >= 26
    assert pubs[0]["estado"] == "To appear" and pubs[0]["anio"] == 2027
    esop = next(x for x in pubs if x["titulo"] == "Elucidating Type Conversions in SQL Engines")
    assert esop["doi"] == "10.1007/978-3-031-91118-7_16" and esop["anio"] == 2025
    assert esop["url_destino"].endswith("yeAl-esop2025.pdf") and "Matías Toro" in esop["autores"]
    assert sum(1 for x in pubs if x["tipo_publicacion"] == "Workshops") == 4

    tesis = out["tesis"]
    assert len(tesis) >= 60
    labrada = next(t for t in tesis if t["estudiante"] == "Elizabeth Labrada")
    assert labrada["titulo"] == "Gradual System F" and labrada["nivel"] == "PhD" and labrada["anio"] == 2023

    fondecyt = next(x for x in out["proyecto"] if x["titulo"].startswith("Gradual Differential Privacy"))
    assert fondecyt["rol"] == "Principal investigator" and fondecyt["anio_inicio"] == 2025

    cc3201 = [d for d in out["dictacion"] if d["codigo_curso"] == "CC3201"]
    assert len(cc3201) == 5 and cc3201[0]["nombre_curso"] == "Bases de Datos" and cc3201[0]["anio"] == 2020
    assert len(out["dictacion"]) >= 20
