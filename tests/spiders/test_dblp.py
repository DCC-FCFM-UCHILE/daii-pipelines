from conftest import fixture_response, run_parse
from scrapy.http import TextResponse

from daii.bronze.spiders.dblp import DblpSpider


def test_dblp_toro():
    resp = fixture_response("dblp_toro.json", "https://sparql.dblp.org/sparql?q", "matias-toro", TextResponse)
    resp.meta["pid"] = "169/6836"
    out = run_parse(DblpSpider().parse(resp))
    assert out["perfil"][0]["identificador"] == "169/6836"
    assert len(out["publicacion"]) >= 20
    p = next(p for p in out["publicacion"] if p["ids"]["dblp"] == "conf/csfw/ArquezTT25")
    assert p["titulo"] == "Gradual Sensitivity Typing"
    assert p["autores"] == ["Damián Árquez", "Matías Toro", "Éric Tanter"]  # ordenados por ordinal
    assert p["doi"] == "10.1109/CSF64896.2025.00021" and p["anio"] == 2025 and p["tipo_publicacion"] == "Inproceedings"
