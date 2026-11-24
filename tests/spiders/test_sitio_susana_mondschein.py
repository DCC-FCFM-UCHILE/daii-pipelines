from conftest import fixture_response, run_parse
from scrapy.http import Response

from daii.bronze.spiders.sites.susana_mondschein import CAMPANIA, SITIO, SusanaMondscheinSpider
from daii.config import academico

P = 'susana-mondschein'
CV = academico(P)['perfiles']['cv']


def test_dii():
    out = run_parse(SusanaMondscheinSpider().parse(fixture_response('mondschein_dii.html', SITIO, P)))
    p = out['persona'][0]
    assert p['nombre'] == 'Susana Mondschein' and 'Adolfo Ibáñez University' in p['bio']  # bytes windows-1252
    assert [(f['grado'], f['institucion']) for f in out['formacion']] == [
        ('Industrial Engineer', 'University of Chile'),
        ('master’s degree in engineering sciences', 'University of Chile'),
        ('Ph.D. in Operations Research', 'Massachusetts Institute of Technology (MIT)'),
    ]
    afil = {a['organizacion']: a for a in out['afiliacion']}
    assert len(afil) == 7
    assert afil['Yale School of Management'] | {'desde': '2001', 'hasta': '2011'} == afil['Yale School of Management']
    assert afil['Center for Cancer Control and Prevention (CECAN)']['rol'] == 'researcher'
    assert afil['National Commission for Evaluation and Productivity (CNEP)']['desde'] == '2022'
    ichio = afil['Chilean Institute of Operations Research (ICHIO)']
    assert (ichio['rol'], ichio['desde'], ichio['hasta']) == ('president', '2021', '2023')
    assert [a['nombre'] for a in out['area']] == ['applied stochastic models', 'Health Management', 'Epidemiology']

    pubs = out['publicacion']
    assert len(pubs) >= 30
    sr = next(x for x in pubs if x['doi'] == '10.1038/s41598-022-07447-2')
    assert sr['titulo'].startswith('Replacing quarantine of COVID-19 contacts')
    assert (sr['venue'], sr['anio'], sr['autores']) == ('Scientific Reports', 2022, ['P. Foncea', 'M. Olivares'])
    assert sr['tipo_publicacion'] == 'JOURNAL ARTICLES'
    assert sum(x['doi'] is not None for x in pubs) >= 20


def test_cv():
    out = run_parse(SusanaMondscheinSpider().parse_cv(fixture_response('mondschein_cv.pdf', CV, P, cls=Response)))
    yale = next(a for a in out['afiliacion'] if a['organizacion'] == 'Yale School of Management')
    assert (yale['rol'], yale['desde'], yale['hasta']) == ('Lecturer', 'September 2001', 'July 2011')
    assert len(out['afiliacion']) >= 15
    assert out['formacion'][0] | {'grado': 'Ph.D. in Operations Research', 'anio': 1993} == out['formacion'][0]
    assert 'Revenue Management' in {a['nombre'] for a in out['area']}
    assert len(out['dictacion']) == 12
    assert {'nombre_curso': 'Capstone project', 'institucion': 'Adolfo Ibañez University'}.items() <= out['dictacion'][
        1
    ].items()
    assert len(out['distincion']) == 8 and out['distincion'][0]['nombre'] == 'Saval Award for best plenary work'
    proys = {x['titulo']: x for x in out['proyecto']}
    f = proys['Pricing policies in dynamic and stochastic environments']
    assert (f['codigo'], f['rol'], f['anio_inicio'], f['anio_fin']) == ('1990990', 'Principal researcher', 1999, 2001)
    assert proys['Healthcare Decision Support Systems']['anio_inicio'] == 2015
    assert len(proys) >= 10


def test_campania():
    # HTML renderizado por Playwright (la SPA sin JS es un <div id="root"> vacío)
    out = run_parse(
        SusanaMondscheinSpider().parse_campania(fixture_response('mondschein_home_rendered.html', CAMPANIA, P))
    )
    tray = out['afiliacion']
    assert {
        'rol': 'Consejera',
        'organizacion': 'Comisión Nacional de Evaluación y Productividad (CNEP)',
    }.items() <= tray[1].items()
    assert (tray[0]['rol'], tray[0]['desde'], tray[0]['hasta']) == ('Profesora Titular', '2023', 'Act')
    dir_dii = next(a for a in tray if a['rol'] == 'Directora del Departamento de ingeniería Industrial')
    assert (dir_dii['desde'], dir_dii['hasta']) == ('octubre 2023', 'presente')
    assert not any('ABET' in a['rol'] for a in tray)  # logros sueltos no son cargos
    assert len(tray) == 15
    assert [(f['grado'], f['institucion'], f['anio']) for f in out['formacion']][0] == (
        'PhD. en Investigación de Operaciones',
        'MIT',
        1993,
    )

    prensa = out['actividad']
    assert len(prensa) >= 50 and {a['tipo_actividad'] for a in prensa} == {'prensa'}
    ciper = next(a for a in prensa if 'CIPER' in a['descripcion'])
    assert ciper['titulo'] == '¿Qué tan efectiva es la cuarentena de 7 días para viajeros?'
    assert ciper['fecha'] == '27 de agosto de 2021'
    assert (
        ciper['url_destino']
        == 'https://www.ciperchile.cl/2021/08/27/que-tan-efectiva-es-la-cuarentena-de-7-dias-para-viajeros/'
    )
    # el programa electoral no se registra
    assert not any('Talento estudiantil' in a['titulo'] for a in prensa)
