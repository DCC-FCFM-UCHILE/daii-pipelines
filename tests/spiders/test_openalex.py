from conftest import fixture_response, run_parse
from scrapy.http import TextResponse

from daii.bronze.spiders.openalex import OpenalexSpider


def test_author():
    resp = fixture_response(
        "openalex_author_silva.json", "https://api.openalex.org/authors/x", "jorge-silva", TextResponse
    )
    out = run_parse(OpenalexSpider().parse_author(resp))
    assert {m["nombre"]: m["valor"] for m in out["metrica"] if m["anio"] is None}["h_index"] == 19
    assert out["perfil"][0]["identificador"] == "A5074503710"
    assert out["area"]


def test_works_paginate():
    req_meta = {"persona": "jorge-silva", "orcid": "0000-0002-0256-282X", "n": 1}
    resp = fixture_response(
        "openalex_works_silva.json", "https://api.openalex.org/works?x", "jorge-silva", TextResponse
    )
    resp.meta.update(req_meta)
    results = list(OpenalexSpider().parse_works(resp))
    out = run_parse(results)
    assert len(out["publicacion"]) == 5
    assert all(p["autores"] and p["ids"]["openalex"].startswith("W") for p in out["publicacion"])
    assert any(not isinstance(r, dict) for r in results)  # pide la siguiente página (page=2)
