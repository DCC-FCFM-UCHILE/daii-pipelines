import asyncio

from conftest import fixture_response, run_parse
from scrapy.http import Response

from daii.bronze.spiders.base import pdf_texto
from daii.bronze.spiders.sites.patricio_felmer import CV, PERSONA, PatricioFelmerSpider


def test_start():
    async def requests(persona):
        return [req async for req in PatricioFelmerSpider(persona=persona).start()]

    (req,) = asyncio.run(requests(PERSONA))
    assert req.url == CV and req.meta == {"persona": PERSONA, "guardar": False}
    assert asyncio.run(requests("rodrigo-palma")) == []


def test_cv():
    spider = PatricioFelmerSpider()
    response = fixture_response("felmer_cv.pdf", CV, PERSONA, Response)
    texto = pdf_texto(response)
    assert all(campo not in texto for campo in ("ESTADO CIVIL", "NACIONALIDAD", "DIRECCIÓN DE TRABAJO", "@"))

    out = run_parse(spider.parse_cv(response))
    assert all(len(out[tipo]) >= minimo for tipo, minimo in spider.expect.items())
    assert {
        "grado": "Ph. D. in Mathematics",
        "institucion": "University of Wisconsin, Madison",
        "anio": 1989,
    }.items() <= out["formacion"][-1].items()
    assert out["distincion"][0]["nombre"] == "Premio Nacional de Ciencias Exactas 2011."
    assert out["distincion"][0]["anio"] == 2011
    assert any(d["nombre"].startswith("Medalla Rectoral") and d["anio"] == 2011 for d in out["distincion"])
    assert {
        "titulo": "Periodic solutions of a coupled system of telegraph-wave equations",
        "autores": ["P. Felmer", "R. Manásevich"],
        "anio": 1986,
    }.items() <= out["publicacion"][0].items()
    publicaciones = {p["titulo"]: p["anio"] for p in out["publicacion"]}
    assert publicaciones["Periodic Solutions of ‘superquadratic’ Hamiltonian systems"] == 1993
    assert publicaciones["Variational Methods in Hamiltonian Systems"] == 1996
