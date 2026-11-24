from conftest import fixture_response, run_parse

from daii.bronze.spiders.ucurriculum import UcurriculumSpider

URL = 'https://dcc.uchile.cl/nosotros/academico/mauricio-cerda/'


def test_ficha_cerda():
    resp = fixture_response('dcc_ficha_cerda.html', URL, 'mauricio-cerda')
    out = run_parse(UcurriculumSpider().parse(resp))

    p = out['persona'][0]
    assert p['nombre'] == 'Mauricio Cerda V.'
    assert p['email'] == 'mcerda@dcc.uchile.cl'
    assert {a['organizacion'] for a in out['afiliacion']} == {'DCC', 'IDIA'}
    assert out['afiliacion'][0]['rol'] == 'Profesor Asociado'
    assert {'grado': 'Doctor', 'institucion': 'Universite NANCY 2', 'anio': 2011}.items() <= out['formacion'][0].items()

    cc5205 = [d for d in out['dictacion'] if d['codigo_curso'] == 'CC5205']
    assert cc5205 and cc5205[0]['anio'] == 2026 and cc5205[0]['semestre'] == 'Otoño'
    assert len(out['dictacion']) > 50  # un ítem por curso × semestre

    assert out['tesis'][0]['anio'] == 2025 and out['tesis'][0]['rol'] == 'Participación como Profesor Guía'
    assert len(out['publicacion']) > 5 and out['publicacion'][0]['anio'] == 2026

    fondecyt = next(x for x in out['proyecto'] if x['codigo'] == '1240954')
    assert fondecyt['fuente'] == 'Fondecyt_Anid' and fondecyt['anio_inicio'] == 2024 and fondecyt['anio_fin'] == 2028
