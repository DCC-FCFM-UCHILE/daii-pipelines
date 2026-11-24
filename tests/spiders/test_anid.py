from conftest import fixture_response, run_parse
from scrapy import Request

from daii.bronze.spiders.anid import AnidSpider
from daii.config import academico

URL = 'https://investigadores.anid.cl/es/public_search/researcher?id=4406'
WORK = 'https://investigadores.anid.cl//es/public_search/work?id={}'
SLUG = 'joaquin-fontbona'


def test_ficha_fontbona():
    gen = list(AnidSpider().parse(fixture_response('anid_4406.html', URL, SLUG)))
    out = run_parse(gen)

    p = out['persona'][0]
    assert p['nombre'] == 'Joaquin Fontbona Torres' and p['cargo'] == 'Profesor Titular'
    assert p['foto_url'] is None  # avatar genérico

    assert [a['nombre'] for a in out['area']] == [
        'Probability Theory',
        'Data Science',
        'Mathematical Foundations of Machine Learning and Artificial Intelligence',
    ]
    f = out['formacion']
    assert len(f) == 3
    assert f[2] == f[2] | {'grado': 'Mathematical engineer', 'institucion': 'UNIVERSIDAD DE CHILE, Chile', 'anio': 1999}

    afil = out['afiliacion']
    assert len(afil) == 14  # institución actual + 7 académicas + 6 profesionales
    assert afil[0] == afil[0] | {'organizacion': 'UNIVERSIDAD DE CHILE', 'rol': 'Profesor Titular'}
    assert afil[2] == afil[2] | {
        'organizacion': 'UNIVERSIDAD DE CHILE, CIENCIAS FÍSICA Y MATEMÁTICAS',
        'rol': 'Associate profesor, Full Time',
        'desde': '2011',
        'hasta': None,
    }
    assert afil[3]['organizacion'] == 'UNIVERSITE PARIS OUEST - PARIS X (NANTERRE)' and afil[3]['hasta'] == '2004'

    (d,) = out['distincion']
    assert d['nombre'] == 'Allocation de Recherche' and d['anio'] == 2000
    assert d['otorgante'] == 'UNIVERSIDAD PIERRE ET MARIE CURIE'

    # 45 obras de la pestaña Producción se piden como páginas propias
    works = [r.url for r in gen if isinstance(r, Request)]
    assert len(works) == 45 and all('public_search/work?id=' in u for u in works)

    # colaboradores: link sin seguir, sin la propia ficha
    links = {x['texto']: x for x in out['link']}
    assert len(links) == 11 and not any(x['seguido'] for x in links.values())
    assert links['Felipe Tobar']['url_destino'].endswith('researcher?id=26903')


def test_obra_articulo():
    (p,) = run_parse(AnidSpider().parse_work(fixture_response('anid_work_863743.html', WORK.format(863743), SLUG)))[
        'publicacion'
    ]
    assert p == p | {
        'titulo': 'STOCHASTIC GRADIENT DESCENT FOR BARYCENTERS IN WASSERSTEIN SPACE',
        'anio': 2025,
        'tipo_publicacion': 'Article',
        'venue': 'Journal of Applied Probability',
        'autores': ['Backhoff-Veraguas; J.; Fontbona; J.; Rios; G.; Tobar; F.'],
        'doi': '10.1017/jpr.2024.39',
        'ids': {'anid': '863743', 'indexacion': 'ISI'},
    }


def test_obra_conferencia():
    (p,) = run_parse(AnidSpider().parse_work(fixture_response('anid_work_1009048.html', WORK.format(1009048), SLUG)))[
        'publicacion'
    ]
    assert p['tipo_publicacion'] == 'ConferencePaper' and p['doi'] == '10.1109/IJCNN64981.2025.11227152'
    assert p['venue'] == 'Proceedings of the International Joint Conference on Neural Networks'


def test_obra_proyecto():
    (p,) = run_parse(AnidSpider().parse_work(fixture_response('anid_work_400279.html', WORK.format(400279), SLUG)))[
        'proyecto'
    ]
    assert p == p | {
        'titulo': 'Large scale behavior of stochastic systems',
        'fuente': 'MathAmSud-CONICYT',
        'anio_inicio': 2015,
        'anio_fin': 2017,
        'codigo': None,
    }


def test_ficha_palza():
    persona = 'humberto-palza'
    url = academico(persona)['perfiles']['anid']
    assert url.endswith('/es/public_search/researcher?id=229')
    gen = list(AnidSpider().parse(fixture_response('palza.html', url, persona)))
    out = run_parse(gen)
    assert out['persona'][0]['nombre'] == 'Humberto Cristian Palza Cordero'
    assert len(out['formacion']) == 3
    assert out['formacion'][0]['grado'] == 'Materials science'
    assert out['formacion'][0]['anio'] == 2006
    assert sum(isinstance(r, Request) and '/es/public_search/work?id=' in r.url for r in gen) >= 20
