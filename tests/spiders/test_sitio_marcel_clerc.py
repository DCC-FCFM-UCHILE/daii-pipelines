import asyncio

from conftest import fixture_response, run_parse

from daii.bronze.spiders.sites.marcel_clerc import PERFIL, PERSONA, PUBLICACIONES, MarcelClercSpider


def test_solicitudes():
    async def solicitudes(persona):
        return [r async for r in MarcelClercSpider(persona=persona).start()]

    perfil, publicaciones = asyncio.run(solicitudes(PERSONA))
    assert perfil.url == PERFIL
    assert perfil.meta['persona'] == PERSONA
    assert perfil.meta['guardar'] is False
    assert publicaciones.url == PUBLICACIONES
    assert publicaciones.meta.get('guardar') is not False
    assert asyncio.run(solicitudes('otro-academico')) == []


def test_perfil():
    spider = MarcelClercSpider()
    response = fixture_response('clerc_perfil.html', PERFIL, PERSONA).replace(encoding='iso-8859-1')
    assert response.xpath('//tr[td[starts-with(normalize-space(.), "Birth date")]]/td[2]//text()').getall() == [
        '[REDACTADO]'
    ]

    out = run_parse(spider.parse(response))
    assert out['persona'][0]['nombre'] == 'Dr. Marcel G. Clerc Gavilan'
    assert out['persona'][0]['cargo'] == 'Full Professor of Physics department at University of Chile.'
    assert out['persona'][0]['foto_url'].endswith('/images/marcel_professional.jpg')
    assert {p['plataforma'] for p in out['perfil']} == {'scholar', 'scopus', 'wos'}
    assert out['link']
    assert '[REDACTADO]' not in str(out)


def test_publicaciones():
    spider = MarcelClercSpider()
    response = fixture_response('clerc_publicaciones.html', PUBLICACIONES, PERSONA).replace(encoding='iso-8859-1')
    pubs = run_parse(spider.parse_publicaciones(response))['publicacion']
    assert len(pubs) >= 200

    primera = pubs[0]
    assert primera['titulo'] == 'Light-self-induced geometric phase structures in liquid crystals'
    assert primera['anio'] == 2026
    assert primera['venue'] == 'PNAS Nexus'
    assert primera['autores'] == ['M. Diaz-Zuniga', 'M. Riquelme-Alcantara', 'M. G. Clerc']

    doi = next(p for p in pubs if p['doi'] == '10.1038/s42005-024-01690-x')
    assert doi['anio'] == 2024
    assert doi['venue'] == 'Commun. Phys.'
    assert doi['url_destino'] == 'https://doi.org/10.1038/s42005-024-01690-x'

    doi_texto = next(p for p in pubs if p['doi'] == '10.1080/02678292.2023.2226626')
    assert doi_texto['venue'] == 'Liquid Crystals'
    assert all('.' not in p['autores'] for p in pubs)

    antigua = next(p for p in pubs if p['titulo'] == 'Dynamics of one-dimensional Cahn-Hilliard model')
    assert antigua['anio'] == 2005
    assert antigua['autores'] == ['M. Argentina', 'R. Rojas', 'E. Tirapegui']
    assert antigua['venue'] == 'Phys. Rev. E'
    assert antigua['url_destino'].endswith('/Pdf/articles/Article21.pdf')
