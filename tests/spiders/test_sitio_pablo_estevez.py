from conftest import fixture_response, run_parse

from daii.bronze.spiders.sites.pablo_estevez import PERSONA, PabloEstevezSpider
from daii.config import academico

HOME = academico(PERSONA)['perfiles']['sitio']


def test_home():
    out = run_parse(PabloEstevezSpider().parse(fixture_response('estevez.html', HOME, PERSONA)))
    assert out['persona'][0]['nombre'] == 'Pablo Estévez'
    assert out['persona'][0]['email'] == 'pestevez@ing.uchile.cl'


def test_info():
    response = fixture_response('estevez-info.html', HOME + 'info.html', PERSONA)
    out = run_parse(PabloEstevezSpider().parse_info(response))
    assert len(out['formacion']) == 4
    assert out['formacion'][0]['grado'] == 'Dr. Eng. (Information Engineering)'
    assert out['formacion'][0]['institucion'] == 'University of Tokyo'
    assert out['formacion'][0]['anio'] == 1995


def test_publicaciones():
    response = fixture_response('estevez-public.html', HOME + 'public.html', PERSONA)
    out = run_parse(PabloEstevezSpider().parse_publicaciones(response))
    assert len(out['publicacion']) >= 25
    assert out['publicacion'][0]['autores'][0] == 'Estévez, P.A.'
    assert out['publicacion'][0]['anio'] == 2006
    assert out['publicacion'][0]['titulo'] == (
        'Subscription Fraud Prevention in Telecommunications Using Fuzzy Rules and Neural Networks'
    )


def test_proyectos():
    response = fixture_response('estevez-projects.html', HOME + 'projects.html', PERSONA)
    out = run_parse(PabloEstevezSpider().parse_proyectos(response))
    assert len(out['proyecto']) >= 8
    assert out['proyecto'][0]['codigo'] == '1030924'
    assert out['proyecto'][0]['anio_inicio'] == 2003
