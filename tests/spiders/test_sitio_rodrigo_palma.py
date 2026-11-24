from asyncio import run
from pathlib import PurePosixPath
from urllib.parse import urlparse

from conftest import fixture_response, run_parse
from scrapy import Request
from scrapy.http import TextResponse

from daii.bronze.spiders.sites.rodrigo_palma import RodrigoPalmaSpider
from daii.config import academico


def test_ficha_y_csv():
    spider = RodrigoPalmaSpider(persona='rodrigo-palma')

    async def solicitudes():
        return [request async for request in spider.start()]

    [ficha] = run(solicitudes())
    assert ficha.url == academico(spider.slug)['perfiles']['sitio']
    response = fixture_response('die/rodrigo_palma.html', ficha.url, spider.slug)
    resultados = list(spider.parse(response))
    perfil = run_parse(resultados)
    assert perfil['persona'][0]['nombre'] == 'Rodrigo Palma'
    assert perfil['formacion'][0]['grado'] == 'Dr. Ing. University of Dortmund, Alemania.'

    csvs = [r for r in resultados if isinstance(r, Request) and r.url.endswith('.csv')]
    assert len(csvs) == 3
    items = {}
    for req in csvs:
        nombre = PurePosixPath(urlparse(req.url).path).name
        csv = fixture_response(f'die/{nombre}', req.url, spider.slug, TextResponse)
        csv.request = req
        items.update(run_parse(req.callback(csv)))
    assert {tipo: len(filas) for tipo, filas in items.items()} == {'publicacion': 42, 'proyecto': 30, 'tesis': 31}
    publicacion = next(p for p in items['publicacion'] if p['doi'] == '10.1109/TPWRD.2024.3476229')
    assert publicacion['anio'] == 2025
    assert publicacion['autores'][0] == 'Ñancupil-Quirilao, Ignacio'
    truncada = next(
        p
        for p in items['publicacion']
        if p['titulo'] == 'What would make an international Power-to-X project successful?'
    )
    assert truncada['autores'][-1] == 'C Carvalho'
    proyecto = next(p for p in items['proyecto'] if p['codigo'] == '1241556')
    assert proyecto['anio_fin'] == 2027
    tesis = next(t for t in items['tesis'] if t['estudiante'] == 'Sepúlveda Figueroa, Vicente Ignacio')
    assert tesis['anio'] == 2024
