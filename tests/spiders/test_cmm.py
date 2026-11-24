from conftest import fixture_response, run_parse

from daii.bronze.spiders.cmm import CmmSpider

URL = 'https://www.cmm.uchile.cl/?persona=alejandro-maass'


def test_ficha_maass():
    out = run_parse(CmmSpider().parse(fixture_response('cmm_maass.html', URL, 'alejandro-maass')))

    p = out['persona'][0]
    assert p['nombre'] == 'Alejandro Maass'
    assert p['cargo'] == 'Investigador Principal | Director de Relaciones Internacionales'
    assert p['email'] == 'amaass@dim.uchile.cl' and p['telefono'] == '+56 2 2978 4456' and p['oficina'] == '724'
    assert p['foto_url'].endswith('maass_alejandro_01.jpg')
    assert p['bio'].startswith('Alejandro Maass holds a PhD') and 'Awards' not in p['bio']

    phd, ing = out['formacion']
    assert phd == phd | {
        'grado': 'Doctor en Matemáticas',
        'institucion': 'Universidad de Aix-Marseille, Francia',
        'anio': 1994,
    }
    assert ing == ing | {'grado': 'Ingeniero Civil Matemático', 'institucion': 'Universidad de Chile', 'anio': 1990}

    afil = {(a['organizacion'], a['rol']) for a in out['afiliacion']}
    assert afil == {
        ('CMM', 'Investigador Principal'),
        ('CMM', 'Director de Relaciones Internacionales'),
        ('Universidad de Chile', 'Profesor Titular'),
    }
    assert [a['nombre'] for a in out['area']] == ['Probabilidad y teoría ergódica', 'CMM Climate & Biodiversity']

    assert len(out['distincion']) == 8
    assert {'nombre': 'National Prize for Exact Sciences', 'anio': 2025}.items() <= out['distincion'][0].items()
    assert out['distincion'][-1]['nombre'] == 'Marcos Orrego Puelma prize of the Chilean Institute of Engineering'

    # sin menú ni taxonomías del sitio: solo los links de contacto/bio
    assert [x['url_destino'] for x in out['link']] == ['https://n9.cl/iv56lo']


def test_ficha_ramirez_sin_bio():
    url = 'https://www.cmm.uchile.cl/?persona=hector-ramirez'
    out = run_parse(CmmSpider().parse(fixture_response('cmm_ramirez.html', url, 'hector-ramirez')))
    p = out['persona'][0]
    assert p['nombre'] == 'Héctor Ramírez' and p['bio'] is None  # su ficha no tiene .cmm-bio
    assert ('Doctorado en Matemáticas Aplicadas', 2005) in {(f['grado'], f['anio']) for f in out['formacion']}
