from conftest import fixture_response, run_parse

from daii.bronze.spiders.cr2 import Cr2Spider

URL = 'https://www.cr2.cl/roberto-rondanelli/'


def test_ficha_rondanelli():
    out = run_parse(Cr2Spider().parse(fixture_response('cr2_rondanelli.html', URL, 'roberto-rondanelli')))

    p = out['persona'][0]
    assert p['nombre'] == 'Roberto Rondanelli' and p['cargo'] == 'Director'
    assert p['email'] == 'ronda@dgf.uchile.cl'
    assert p['foto_url'].endswith('RobertoRondanelli_200.jpg')
    assert p['bio'].startswith('Profesor asociado del Departamento de Geofísica')

    afil = {(a['organizacion'], a['rol']) for a in out['afiliacion']}
    assert afil == {
        ('CR2', 'Director'),
        ('Departamento de Geofísica de la Universidad de Chile', 'Profesor asociado'),
    }
    (f,) = out['formacion']
    assert f == f | {
        'grado': 'doctorado',
        'institucion': 'Massachusetts Institute of Technology (MIT), Estados Unidos',
        'anio': None,
    }

    perf = {x['plataforma']: x for x in out['perfil']}
    assert set(perf) == {'orcid', 'researchgate', 'scholar'}
    assert perf['orcid']['identificador'] == '0000-0002-7440-7810'

    pubs = out['publicacion']
    assert len(pubs) == 50
    t = pubs[0]
    assert t == t | {
        'titulo': 'Tornado Seasonality in Central-Southern Chile',
        'venue': 'Geophysical Research Letters',
        'autores': ['Caballero-Morán, V.', 'Rondanelli, R.'],
        'anio': 2025,
        'doi': '10.1029/2024GL110900',
        'url_destino': 'https://doi.org/10.1029/2024GL110900',
        'tipo_publicacion': 'revista',
        'ids': {
            'linea_cr2': 'Zonas Costeras',
            'indexacion': 'Thomson Reuters ISI (SCIE)',
            'acceso': 'All Open Access; Gold Open Access',
            'issn': '0094-8276',
        },
    }
    assert pubs[-1]['anio'] == 2013 and pubs[-1]['doi'] == '10.1002/jgrd.50293'

    # sin menú del sitio: solo links de contacto y de la tabla
    urls = [x['url_destino'] for x in out['link']]
    assert 'https://orcid.org/0000-0002-7440-7810' in urls and not any('cr2.cl' in u for u in urls)
