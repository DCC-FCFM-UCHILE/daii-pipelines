from conftest import fixture_response, run_parse

from daii.bronze.spiders.sites.leonardo_bronfman import PERSONA, LeonardoBronfmanSpider
from daii.config import academico


def test_astronomia():
    response = fixture_response('bronfman.html', academico(PERSONA)['perfiles']['sitio'], PERSONA)
    out = run_parse(LeonardoBronfmanSpider().parse(response))
    assert out['persona'][0]['nombre'] == 'Leonardo Bronfman'
    assert out['formacion'][1]['institucion'] == 'Universidad de Columbia'
    assert out['formacion'][1]['anio'] == 1986
    assert len(out['publicacion']) == 10
    assert out['publicacion'][0]['titulo'] == 'A deep CO survey of molecular clouds in the Southern Milky Way'
    assert out['publicacion'][0]['anio'] == 1989
    titulos = {p['anio']: p['titulo'] for p in out['publicacion']}
    assert titulos[2008].endswith('de velocidad extremadamente alta en Norma')
    assert titulos[2013] == 'Observaciones con ALMA del flujo molecular de salida molecular masivo G331.512-0.103'
    assert len(out['distincion']) == 3
    assert out['distincion'][0]['anio'] == 1992
