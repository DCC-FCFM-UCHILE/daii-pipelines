import pytest
from conftest import fixture_response, run_parse

from daii.bronze.spiders.portafolio import PortafolioSpider

URL = 'https://portafolio-academico.uchile.cl/perfil/27103-James-Peter-Mc-Phee-Torres'


def test_portafolio_mcphee_pagina_1():
    resp = fixture_response('portafolio_mcphee_rendered.html', URL, 'james-mcphee')
    out = run_parse(PortafolioSpider().parse_static(resp))

    p = out['persona'][0]
    assert p['nombre'] == 'James Peter Mc Phee Torres' and p['email'] == 'jmcphee@ing.uchile.cl'
    roles = {a['rol'] for a in out['afiliacion']}
    assert 'Prof. Titular · Categoría académica ordinaria · Jornada: 44 hrs' in roles
    assert 'Vicerrector/a De Investigacion Y Desarrollo' in roles
    assert {'grado': 'Doctor', 'institucion': 'U. of California - Los Angeles', 'anio': 2004}.items() <= out[
        'formacion'
    ][0].items()

    d = out['dictacion'][0]
    assert (d['codigo_curso'], d['anio'], d['semestre']) == ('CD1100', 2026, 'Primer Semestre')
    pub = out['publicacion'][0]
    assert pub['doi'] == 'http://dx.doi.org/10.5194/tc-20-1895-2026'  # crudo; silver normaliza
    assert pub['ids']['indexacion'] == 'WOS/SCOPUS/UCH/VID'
    assert out['proyecto'][0]['codigo'] == 'CIA250010' and out['proyecto'][0]['anio_fin'] == 2030
    assert out['tesis'][0]['estudiante'] == 'Castillo Ávalos, Yuri Alejandro'
    assert out['actividad'][0]['rol'] == 'Colaborador(a)'
    # página 1 de cada tabla: 10 por tabla paginada
    assert len(out['dictacion']) == 10 and len(out['publicacion']) >= 10


def test_portafolio_meruane_pestania_bio_opcional():
    url = 'https://portafolio-academico.uchile.cl/perfil/61060-Viviana-Isabel-Meruane-Naranjo'
    out = run_parse(PortafolioSpider().parse_static(fixture_response('portafolio_meruane_rendered.html', url, 'x')))
    assert out['persona'][0]['bio'].startswith('Soy Viviana Meruane, Profesora Titular')
    assert len(out['dictacion']) == 10 and len(out['tesis']) == 10  # página 1 de cada tabla


def test_portafolio_reprocesa_fragmento_archivado(tmp_path, monkeypatch):
    import gzip
    import json

    from parsel import Selector

    from daii.bronze import middlewares

    monkeypatch.setattr(middlewares, 'BRONZE', tmp_path)
    spider = PortafolioSpider(run_id='prueba')
    resp = fixture_response('portafolio_mcphee_rendered.html', URL, 'james-mcphee')
    resp.meta['observacion_id'] = 'inicial'
    table = resp.css('#justify-tab-example-tabpane-docencia table')[0]
    fragment = spider._archive_table(resp, 'docencia', 0, 2, table)
    run = tmp_path / 'portafolio' / 'prueba'
    entry = json.loads((run / 'pages.jsonl').read_text())
    assert (entry['pestania'], entry['tabla'], entry['pagina']) == ('docencia', 0, 2)
    assert entry['observacion_padre'] == 'inicial'
    assert entry['observacion_id'] == fragment
    saved = gzip.decompress((run / entry['file']).read_bytes()).decode()
    parsed = run_parse(spider.parse_static(resp, extra=[('docencia', Selector(text=saved), fragment)]))
    courses = parsed['dictacion']
    assert len(courses) == 20
    assert courses[0]['observacion_id'] == 'inicial'
    assert courses[10]['observacion_id'] == fragment
    assert courses[10]['codigo_curso'] == 'CD1100'


class _Locator:
    def __init__(self, n: int, text: str = ''):
        self.n, self.text = n, text

    async def count(self):
        return self.n

    def nth(self, _):
        return self

    async def inner_text(self):
        return self.text


class _Page:
    """Lo mínimo de una página Playwright que usa `_paginar` antes de pasar de página."""

    def __init__(self, tables: int, paginators: int, counter: str):
        self.tables, self.paginators, self.counter = tables, paginators, counter

    async def click(self, _):
        pass

    def locator(self, selector: str):
        if selector.endswith(' table'):
            return _Locator(self.tables)
        if 'paginadorTexto' in selector:
            return _Locator(self.paginators, self.counter)
        return _Locator(1)  # el panel


def _paginar(page: _Page) -> list:
    import asyncio

    fragments: list = []
    asyncio.run(PortafolioSpider()._paginar(page, 'docencia', None, fragments))
    return fragments


def test_paginar_tabla_de_una_pagina_no_falla():
    assert _paginar(_Page(tables=2, paginators=2, counter='Página 1 de 1')) == []


@pytest.mark.parametrize(
    ('page', 'error'),
    [
        (_Page(tables=2, paginators=1, counter='Página 1 de 1'), 'paginadores irreconocibles'),
        (_Page(tables=1, paginators=1, counter='Sin resultados'), 'contador de páginas irreconocible'),
    ],
)
def test_paginar_detecta_estructura_desconocida(page, error):
    with pytest.raises(ValueError, match=error):
        _paginar(page)
