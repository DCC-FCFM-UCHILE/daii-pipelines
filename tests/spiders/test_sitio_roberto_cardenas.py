from asyncio import run
from pathlib import PurePosixPath
from urllib.parse import urlparse

from conftest import fixture_response, run_parse
from scrapy import Request
from scrapy.http import TextResponse

from daii.bronze.spiders.sites.roberto_cardenas import RobertoCardenasSpider
from daii.config import academico


def test_ficha_y_csv():
    spider = RobertoCardenasSpider(persona="roberto-cardenas")

    async def solicitudes():
        return [request async for request in spider.start()]

    [ficha] = run(solicitudes())
    assert ficha.url == academico(spider.slug)["perfiles"]["sitio"]
    response = fixture_response("die/roberto_cardenas.html", ficha.url, spider.slug)
    resultados = list(spider.parse(response))
    perfil = run_parse(resultados)
    assert perfil["persona"][0]["nombre"] == "Roberto Cárdenas"
    assert perfil["formacion"][0]["grado"] == "Ph.D. University of Nottingham, U.K."

    csvs = [r for r in resultados if isinstance(r, Request) and r.url.endswith(".csv")]
    assert len(csvs) == 3
    items = {}
    for req in csvs:
        nombre = PurePosixPath(urlparse(req.url).path).name
        csv = fixture_response(f"die/{nombre}", req.url, spider.slug, TextResponse)
        csv.request = req
        items.update(run_parse(req.callback(csv)))
    assert {tipo: len(filas) for tipo, filas in items.items()} == {"publicacion": 61, "proyecto": 20, "tesis": 6}
    publicacion = next(p for p in items["publicacion"] if p["doi"] == "10.35833/MPCE.2024.000654")
    assert publicacion["anio"] == 2025
    proyecto = next(p for p in items["proyecto"] if p["codigo"] == "1230596")
    assert proyecto["anio_fin"] == 2027
    tesis = next(t for t in items["tesis"] if t["estudiante"] == "Moreno Vásquez, Benjamín Andrés")
    assert tesis["anio"] == 2024
