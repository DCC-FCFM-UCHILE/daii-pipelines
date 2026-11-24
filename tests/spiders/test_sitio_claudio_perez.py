from conftest import fixture_response, run_parse

from daii.bronze.spiders.sites.claudio_perez import PERSONA, ClaudioPerezSpider
from daii.config import academico


def test_fondef():
    response = fixture_response('fondef.html', academico(PERSONA)['perfiles']['sitio'], PERSONA)
    out = run_parse(ClaudioPerezSpider().parse(response))
    assert out['persona'][0]['nombre'] == 'CLAUDIO ANDRES PEREZ FLORES'
    assert len(out['proyecto']) >= 6
    proyectos = [p for p in out['proyecto'] if p['codigo'] == 'D08I1060']
    assert {p['rol'] for p in proyectos} == {'DIRECCION GENERAL DEL PROYECTO', 'INVESTIGADOR PRINCIPAL'}
