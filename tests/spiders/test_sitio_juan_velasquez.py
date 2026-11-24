from asyncio import run

from conftest import fixture_response, run_parse
from scrapy import Request

from daii.bronze.spiders.sites.juan_velasquez import DII, PERSONA, WIC, JuanVelasquezSpider


async def semillas(spider):
    return [request async for request in spider.start()]


def test_semillas():
    requests = run(semillas(JuanVelasquezSpider(persona=PERSONA)))
    assert {(r.url, r.meta['persona']) for r in requests} == {(DII, PERSONA), (WIC, PERSONA)}
    assert next(r for r in requests if r.url == WIC).meta['guardar'] is False
    assert run(semillas(JuanVelasquezSpider(persona='rodrigo-palma'))) == []


def test_dii():
    spider = JuanVelasquezSpider()
    run(semillas(spider))
    response = fixture_response('velasquez_dii.html', DII, PERSONA)
    out = run_parse(spider.parse_dii(response))
    (perfil,) = out['persona']
    assert perfil['nombre'] == 'Juan Velásquez'
    assert perfil['cargo'] == 'Profesor Titular'
    assert perfil['email'] == 'jvelasqu@dii.uchile.cl'
    assert perfil['foto_url'].endswith('05072022-14-400x600.jpg')
    assert out['afiliacion'][0]['rol'] == 'Profesor Titular'
    assert len(out['formacion']) == 6
    assert any(
        f['grado'] == 'M.Sc. Computer Science' and f['institucion'] == 'Universidad de Chile' for f in out['formacion']
    )
    assert len(out['area']) == 5
    assert len(out['dictacion']) == 9
    assert out['dictacion'][0]['nombre_curso'] == 'Diseño de Sistemas de Información Administrativos'
    assert {link['url_destino'] for link in out['link']} == {
        'http://wic.uchile.cl/',
        'https://www.linkedin.com/in/juan-velasquez-7800725',
    }
    assert all(link['seguido'] is False for link in out['link'])


def test_wic():
    spider = JuanVelasquezSpider()
    response = fixture_response('velasquez_wic.html', WIC, PERSONA)
    resultados = list(spider.parse_wic(response))
    assert not any(isinstance(resultado, Request) for resultado in resultados)
    out = run_parse(resultados)
    assert set(out) == {'afiliacion', 'area', 'link'}
    (afiliacion,) = out['afiliacion']
    assert (afiliacion['organizacion'], afiliacion['rol']) == ('Web Intelligence Centre', 'Director Académico')
    assert {a['nombre'] for a in out['area']} == {'Deep Learning', 'Data Science', 'health engineering'}
    assert [link['url_destino'] for link in out['link']] == ['https://www.linkedin.com/in/jdvsilva/']
    assert {item['persona'] for items in out.values() for item in items} == {PERSONA}
